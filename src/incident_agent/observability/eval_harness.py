import json
from time import perf_counter
from ..models import Alert, EvalTurn
from ..memory.hindsight import IncidentMemory
from ..llm.groq_client import GroqAgent
from ..llm.tool_loop import run_incident

async def evaluate(cfg,alerts,postmortems):
    local=cfg.model_copy(update={"remote_memory":False,"groq_api_key":""})
    memory=IncidentMemory(local)
    turns=[]
    for index in range(10):
        alert=Alert.model_validate(alerts[index%3])
        start=perf_counter()
        state=await run_incident(alert,memory,GroqAgent(local),local)
        top=state.memories[0] if state.memories else None
        turns.append(EvalTurn(turn=index+1,bank_size=len(memory.documents),recall_fact_count=len(state.memories),
            top_reranker_score=top["scores"]["reranker"] if top else 0,
            facts_used=len(state.plan["evidence_ids"]),mttr_minutes=state.projected_mttr_minutes,
            measured_latency_ms=round((perf_counter()-start)*1000,3),
            precision_at_1=float(bool(top and top["metadata"]["incident_id"]==postmortems[index%3]["incident_id"]))
        ).model_dump())
        await memory.retain(postmortems[index%3])
    cfg.data_dir.mkdir(parents=True,exist_ok=True)
    path=cfg.data_dir/"eval.jsonl"
    path.write_text("".join(json.dumps(row)+"\n" for row in turns))
    return turns
