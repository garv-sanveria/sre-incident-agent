from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from pydantic import BaseModel, Field
from ..models import PostMortem

router=APIRouter()

async def retain_job(app,job,pm):
    try:
        result=await app.memory.retain(pm)
        app.jobs[job]={"status":"completed",**result}
    except Exception as exc:
        app.jobs[job]={"status":"failed","error":type(exc).__name__}

@router.post("/api/postmortems",status_code=202)
async def postmortem(pm:PostMortem,background:BackgroundTasks,request:Request):
    app=request.app.state
    job=uuid4().hex
    if len(app.jobs)>=1000:
        app.jobs.pop(next(iter(app.jobs)))
    app.jobs[job]={"status":"queued"}
    background.add_task(retain_job,app,job,pm)
    return {"job_id":job,"status":"queued"}

@router.get("/api/postmortems/jobs/{job_id}")
async def job_status(job_id:str,request:Request):
    job=request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(404,"Job not found")
    return job

class Reflection(BaseModel):
    query:str=Field(default="Which recurring causes and prevention actions appear?",max_length=1800)

@router.post("/reflect")
async def reflect(body:Reflection,request:Request):
    return await request.app.state.memory.reflect(body.query)
