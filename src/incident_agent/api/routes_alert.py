import asyncio
import hashlib
import json
from time import monotonic
from fastapi import APIRouter, Request, HTTPException
from ..models import Alert
from ..memory.schema import stack_trace_hash
from ..memory.hindsight import IncidentMemory
from ..llm.groq_client import GroqAgent
from ..llm.tool_loop import run_incident
from ..observability.eval_harness import evaluate

router=APIRouter()

async def run(request,alert,memory,simulation):
    app=request.app.state
    llm=GroqAgent(app.cfg)
    state=await run_incident(alert,memory,llm,app.cfg,simulation)
    app.metrics.record(state)
    app.latest=state.public()
    return app.latest

@router.post("/webhook/alert")
async def webhook(alert:Alert,request:Request):
    app=request.app.state
    key=hashlib.sha256(json.dumps([alert.service,alert.environment,alert.error_code,
        stack_trace_hash(alert.top_frames)],sort_keys=True).encode()).hexdigest()
    async with app.ingest_lock:
        now=monotonic()
        app.dedupe={k:v for k,v in app.dedupe.items() if now-v[0]<300}
        if key in app.dedupe:
            return {"deduplicated":True,"incident":app.dedupe[key][1]}
        result=await run(request,alert,app.memory,False)
        app.dedupe[key]=(now,result)
        return {"deduplicated":False,"incident":result}

def demo_guard(request):
    if not request.app.state.cfg.demo_enabled:
        raise HTTPException(404,"Demo endpoints disabled")

@router.post("/api/demo/cold")
async def cold(request:Request):
    demo_guard(request)
    app=request.app.state
    async with app.demo_lock:
        cfg=app.cfg.model_copy(update={"remote_memory":False})
        return await run(request,Alert.model_validate(app.alerts[3]),IncidentMemory(cfg),True)

@router.post("/api/demo/seed")
async def seed(request:Request):
    demo_guard(request)
    app=request.app.state
    async with app.demo_lock:
        for pm in app.postmortems:
            await app.memory.retain(pm)
        return {"count":len(app.memory.documents),"backend":app.memory.backend}

@router.post("/api/demo/warm")
async def warm(request:Request):
    demo_guard(request)
    app=request.app.state
    async with app.demo_lock:
        return await run(request,Alert.model_validate(app.alerts[4]),app.memory,True)

@router.post("/api/demo/eval")
async def evaluation(request:Request):
    demo_guard(request)
    app=request.app.state
    async with app.demo_lock:
        app.evaluation=await evaluate(app.cfg,app.alerts,app.postmortems)
        return {"turns":app.evaluation,"measurement":"MTTR is projected; latency and retrieval are measured"}

@router.get("/api/state")
async def current(request:Request):
    app=request.app.state
    return {"count":len(app.memory.documents),"backend":app.memory.backend,"latest":app.latest,
        "model":app.latest.get("model_id",app.startup_model),"evaluation":app.evaluation}
