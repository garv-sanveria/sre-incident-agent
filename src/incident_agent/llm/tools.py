from pydantic import BaseModel, ConfigDict, Field
from ..state import Phase

class EmptyArgs(BaseModel):
    model_config=ConfigDict(extra="forbid")
class StepArgs(EmptyArgs):
    runbook_id: str
    step: str
class MessageArgs(EmptyArgs):
    message: str = Field(min_length=1,max_length=4000)
class ToolCall(EmptyArgs):
    name: str
    arguments: dict = Field(default_factory=dict)

ARGUMENTS={"k8s_logs":EmptyArgs,"metrics_query":EmptyArgs,"git_diff":EmptyArgs,
    "run_runbook_step":StepArgs,"page_oncall":MessageArgs,
    "band_send_message":MessageArgs,"band_no_reply":EmptyArgs}
SCHEMAS=[{"type":"function","function":{"name":name,"description":{
    "k8s_logs":"Read scoped incident pod logs", "metrics_query":"Read fresh independent telemetry",
    "git_diff":"Read the scoped deployment change", "run_runbook_step":"Apply an allowlisted step subject to server policy",
    "page_oncall":"Record an escalation for human review", "band_send_message":"Conclude with a Band protocol message",
    "band_no_reply":"Conclude Band turn without a room message"}[name],"parameters":model.model_json_schema()}}
    for name,model in ARGUMENTS.items()]

async def dispatch(call,state,sandbox,cfg):
    if call.name not in ARGUMENTS:
        raise ValueError("Unknown tool")
    args=ARGUMENTS[call.name].model_validate(call.arguments).model_dump()
    state.consume(call.name,args)
    if call.name=="k8s_logs":
        result={"source":"simulation","error":state.alert.error_class,"frames":state.alert.top_frames,"symptom":state.alert.symptom}
    elif call.name=="metrics_query":
        result=sandbox.metrics()
    elif call.name=="git_diff":
        result={"source":"simulation","version":state.alert.version,"change":
            "PricingCache TTL removed" if state.alert.version=="v2.14" else "Inspect current rollout and dependency failures"}
    elif call.name=="run_runbook_step":
        result=sandbox.execute(state,args["runbook_id"],args["step"],cfg.final_floor)
        state.mark(Phase.EXECUTING,args["step"])
    elif call.name=="page_oncall":
        result={"queued_for_human":True,"delivered":False,"message":args["message"],"transport":"local-outbox"}
        state.mark(Phase.AWAITING_APPROVAL,args["message"])
    else:
        result={"tool":call.name,"arguments":args,"delivered":False,"transport":"protocol-preview"}
        state.band_output=result
    state.executed_steps[-1].update(ok=True,result=result)
    state.timeline.append({"phase":state.phase.value,"tool":call.name,"result":result})
    return result
