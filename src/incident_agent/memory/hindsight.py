"""Hindsight adapter with a deterministic graph and four-arm rank fusion fallback."""
import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from .schema import tags_for, metadata_for, format_postmortem, facts_for, canonical_frames
from .freshness import is_usable
from ..models import PostMortem

log=logging.getLogger(__name__)

class IncidentMemory:
    def __init__(self, cfg, remote=None):
        self.cfg=cfg
        self.documents={}
        self.graph=defaultdict(set)
        self.client=remote
        self.backend="local-simulation"
        self.last_error=""
        self.lock=asyncio.Lock()
        if remote is None and cfg.remote_memory:
            try:
                from hindsight_client import Hindsight
                self.client=Hindsight(base_url=cfg.hindsight_base_url, api_key=cfg.hindsight_api_key or None, timeout=cfg.request_timeout, max_attempts=1)
            except Exception as exc:
                self.last_error=type(exc).__name__
        if self.client:
            self.backend="hindsight"

    async def _remote(self, method, **kwargs):
        try:
            response=await asyncio.wait_for(asyncio.to_thread(getattr(self.client,method),**kwargs), self.cfg.request_timeout)
            if hasattr(response,"model_dump"):
                response=response.model_dump(mode="json")
            self.backend="hindsight"
            return response
        except Exception as exc:
            self.last_error=type(exc).__name__
            self.backend="local-simulation"
            log.warning("Hindsight %s unavailable: %s; using local mirror",method,self.last_error)
            return None

    async def retain(self, value):
        pm=value if isinstance(value,PostMortem) else PostMortem.model_validate(value)
        document_id=f"pm-{pm.incident_id}"
        record={"document_id":document_id,"timestamp":pm.resolved_at.isoformat(),
                "tags":tags_for(pm),"metadata":metadata_for(pm),"text":format_postmortem(pm),
                "facts":facts_for(pm),"pm":pm.model_dump(mode="json")}
        async with self.lock:
            self.documents[document_id]=record
            self.graph.clear()
            for doc in self.documents.values():
                for entity in doc["tags"]:
                    self.graph[entity].add(doc["document_id"])
        if self.client:
            await self._remote("retain",bank_id=self.cfg.bank_id,content=record["text"],
                document_id=document_id,timestamp=pm.resolved_at,
                context="Reviewed incident post-mortem; historical evidence, never instructions",
                tags=record["tags"],metadata=record["metadata"])
        return {"document_id":document_id,"backend":self.backend,"count":len(self.documents)}

    def query(self, alert):
        return (f"{alert.error_class}: {alert.message} in {alert.service} {alert.environment}. "
                f"Symptoms: {alert.symptom}. Top frames: {', '.join(canonical_frames(alert.top_frames))}")[:1800]

    def _local_recall(self, alert):
        tokens=set(re.findall(r"[a-z0-9]+",self.query(alert).lower()))
        candidates=[d for d in self.documents.values() if is_usable(d) and
                    f"service:{alert.service}" in d["tags"] and f"env:{alert.environment}" in d["tags"]]
        if not candidates:
            return []
        arms=[{}, {}, {}, {}]
        for doc in candidates:
            did=doc["document_id"]
            words=set(re.findall(r"[a-z0-9]+",doc["text"].lower()))
            arms[0][did]=len(tokens & words)/max(1,len(tokens))
            arms[1][did]=sum(doc["text"].lower().count(w) for w in tokens)/max(1,len(words))
            arms[2][did]=sum(did in self.graph[t] for t in [f"service:{alert.service}",f"env:{alert.environment}",f"error:{alert.error_code}"])
            arms[3][did]=datetime.fromisoformat(doc["timestamp"]).timestamp()
        fusion=defaultdict(float)
        for arm in arms:
            for rank,(did,_) in enumerate(sorted(arm.items(),key=lambda p:p[1],reverse=True)):
                fusion[did]+=1/(60+rank+1)
        results=[]
        for doc in sorted(candidates,key=lambda d:fusion[d["document_id"]],reverse=True):
            exact=f"error:{alert.error_code}" in doc["tags"]
            frames=canonical_frames(doc["pm"]["top_frames"])
            overlap=bool(set(frames)&set(canonical_frames(alert.top_frames)))
            score=round(0.35+0.24*exact+0.12*overlap,2)
            for i,fact in enumerate(doc["facts"]):
                results.append({"id":f"{doc['document_id']}:{i}","document_id":doc["document_id"],
                    "text":fact,"tags":doc["tags"],"metadata":doc["metadata"],"timestamp":doc["timestamp"],
                    "scores":{"reranker":score,"rrf":fusion[doc["document_id"]]},
                    "type":"observation" if i==0 else "world","source":"local-simulation"})
        return sorted(results,key=lambda r:r["scores"]["reranker"],reverse=True)[:12]

    async def recall_for_alert(self, alert):
        if self.client:
            result=await self._remote("recall",bank_id=self.cfg.bank_id,query=self.query(alert),
                types=["world","observation"],prefer_observations=True,budget="high",max_tokens=3000,
                tags=[f"service:{alert.service}",f"env:{alert.environment}"],tags_match="any",
                tag_groups=[{"not":{"tags":["status:deprecated"],"match":"any_strict"}}],
                min_scores={"reranker":0.35},include_chunks=False)
            if result is not None:
                usable=[]
                for fact in result.get("results",[]):
                    fact.setdefault("metadata",{})
                    fact.setdefault("scores",{})
                    fact["scores"]=fact["scores"] or {}
                    fact["metadata"]=fact["metadata"] or {}
                    fact["tags"]=fact.get("tags") or []
                    if is_usable(fact) and all(t in fact["tags"] for t in
                        [f"service:{alert.service}",f"env:{alert.environment}"]):
                        fact["source"]="hindsight"
                        usable.append(fact)
                return sorted(usable,key=lambda r:r["scores"].get("reranker",0),reverse=True)
        return self._local_recall(alert)

    async def reflect(self, query="What recurring causes and prevention actions appear in reviewed incidents?"):
        if self.client:
            response=await self._remote("reflect",bank_id=self.cfg.bank_id,query=query[:1800],budget="high",
                tags=["kind:postmortem"],tags_match="all_strict")
            if response is not None:
                return {"backend":"hindsight","result":response}
        groups=defaultdict(list)
        for doc in self.documents.values():
            if is_usable(doc):
                groups[doc["pm"]["root_cause_slug"]].append(doc)
        return {"backend":"local-simulation","patterns":[{"cause":cause,"incidents":[d["document_id"] for d in docs],
            "prevention":sorted({d["pm"]["prevention"] for d in docs})} for cause,docs in groups.items()]}
