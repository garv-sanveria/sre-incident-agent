from ..state import IncidentState, Phase
from ..models import Plan, Hypothesis
from ..execution.policy import RUNBOOKS, fast_path_confident, conflicting_fixes, eligible
from ..execution.runbook_runner import Sandbox
from ..execution.verifier import verify_telemetry
from .tools import dispatch, ToolCall

async def run_incident(alert,memory,llm,cfg,simulation=True):
    state=IncidentState(alert=alert,max_tool_calls=cfg.max_tool_calls,simulation=simulation)
    sandbox=Sandbox(alert)
    state.memories=await memory.recall_for_alert(alert)
    state.conflict=conflicting_fixes(state.memories,alert,cfg.final_floor)
    state.memory_cold=not fast_path_confident(state.memories,alert,cfg.final_floor)
    state.mark(Phase.RECALLED,f"{len(state.memories)} facts; backend={memory.backend}")
    if not state.memory_cold:
        evidence=next(m for m in state.memories[:3] if eligible(m,alert,cfg.final_floor) and m["metadata"].get("runbook_id") in RUNBOOKS)
        rb=evidence["metadata"]["runbook_id"]
        ids=[m.get("id",m.get("document_id")) for m in state.memories if m["document_id"]==evidence["document_id"]]
        plan=Plan(summary=evidence["metadata"]["root_cause"],runbook_id=rb,steps=RUNBOOKS[rb]["steps"],evidence_ids=ids,requires_approval=not simulation)
        state.hypotheses=[Hypothesis(cause=plan.summary,confidence=evidence["scores"]["reranker"],evidence_ids=ids).model_dump()]
        state.projected_mttr_minutes=9
    else:
        plan=Plan(summary="Conflicting historical fixes: stop for human review" if state.conflict else "No verified matching precedent. Inspect logs, metrics and rollout; request human approval.")
    state.plan=plan.model_dump()
    state.mark(Phase.DIAGNOSED,plan.summary)
    if state.conflict or not simulation:
        await dispatch(ToolCall(name="page_oncall",arguments={"message":plan.summary+"; live execution requires an operator."}),state,sandbox,cfg)
    else:
        for turn in range(cfg.max_tool_calls-1):
            call=await llm.step(state)
            state.model_id=llm.model_id
            if call.name in {"band_send_message","band_no_reply"}:
                break
            try:
                result=await dispatch(call,state,sandbox,cfg)
                llm.record_tool_result(result)
            except (PermissionError,ValueError,RuntimeError) as exc:
                state.mark(Phase.AWAITING_APPROVAL,str(exc))
                llm.record_tool_result({"error":str(exc)})
                break
        if sandbox.completed:
            state.verification=await verify_telemetry(sandbox,simulation=True)
            if state.verification["passed"]:
                state.mark(Phase.VERIFIED,"Independent sandbox telemetry assertions passed")
                state.mark(Phase.RESOLVED,"Simulated resolution; no production systems changed")
            else:
                state.mark(Phase.ESCALATED,"Telemetry verification failed")
        elif state.phase!=Phase.AWAITING_APPROVAL:
            if state.tool_calls<cfg.max_tool_calls-1:
                await dispatch(ToolCall(name="page_oncall",arguments={"message":plan.summary}),state,sandbox,cfg)
            else:
                state.mark(Phase.ESCALATED,"Tool budget exhausted; human review required")
    state.model_id=llm.model_id
    await dispatch(ToolCall(name="band_send_message",arguments={"message":
        f"{alert.incident_id}: {state.phase.value}. {plan.summary} "
        f"Evidence: {', '.join(sorted({m['document_id'] for m in state.memories})) or 'none'}. "
        f"Telemetry verified: {state.verification.get('passed',False)}. Simulation={simulation}."}),state,sandbox,cfg)
    return state
