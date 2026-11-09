import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .config import Settings
from .memory.hindsight import IncidentMemory
from .llm.groq_client import GroqAgent
from .observability.tracing import Metrics
from .api import routes_alert, routes_postmortem

logging.basicConfig(level=logging.INFO)
STATIC=Path(__file__).parent/"static"

def create_app(cfg=None):
    cfg=cfg or Settings()
    @asynccontextmanager
    async def lifespan(app):
        app.state.cfg=cfg
        app.state.memory=IncidentMemory(cfg)
        app.state.metrics=Metrics()
        app.state.startup_model=GroqAgent(cfg).model_id
        app.state.latest={}
        app.state.evaluation=[]
        app.state.dedupe={}
        app.state.jobs={}
        app.state.ingest_lock=asyncio.Lock()
        app.state.demo_lock=asyncio.Lock()
        app.state.alerts=json.loads((cfg.fixtures_dir/"incidents/incidents.json").read_text())
        app.state.postmortems=yaml.safe_load((cfg.fixtures_dir/"postmortems/postmortems.yaml").read_text())
        yield
    app=FastAPI(title="SRE Incident Agent",version="1.0.0",lifespan=lifespan)
    @app.middleware("http")
    async def boundary(request:Request,call_next):
        if request.url.path not in ("/","/healthz") and not request.url.path.startswith("/static/"):
            if cfg.api_token:
                if not secrets.compare_digest(request.headers.get("authorization",""),"Bearer "+cfg.api_token):
                    return JSONResponse({"detail":"Authentication required"},status_code=401)
            elif request.client and request.client.host not in ("127.0.0.1","::1","localhost","testclient"):
                return JSONResponse({"detail":"Configure API_TOKEN for non-loopback access"},status_code=403)
        length=request.headers.get("content-length","0")
        try:
            if int(length)>262144:
                return JSONResponse({"detail":"Request too large"},status_code=413)
        except ValueError:
            return JSONResponse({"detail":"Invalid content length"},status_code=400)
        if request.method in ("POST","PUT","PATCH"):
            payload=bytearray()
            async for chunk in request.stream():
                payload.extend(chunk)
                if len(payload)>262144:
                    return JSONResponse({"detail":"Request too large"},status_code=413)
            request._body=bytes(payload)
        response=await call_next(request)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["X-Frame-Options"]="DENY"
        response.headers["Referrer-Policy"]="no-referrer"
        return response
    @app.get("/")
    async def index():
        return FileResponse(STATIC/"index.html")
    @app.get("/healthz")
    async def health():
        return {"status":"ok","memory_backend":app.state.memory.backend,"execution":"sandbox-only"}
    @app.get("/metrics",response_class=PlainTextResponse)
    async def metrics():
        return app.state.metrics.prometheus()
    app.mount("/static",StaticFiles(directory=STATIC),name="static")
    app.include_router(routes_alert.router)
    app.include_router(routes_postmortem.router)
    return app

app=create_app()
