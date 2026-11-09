import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from fastapi.testclient import TestClient
from incident_agent.config import Settings
from incident_agent.models import Alert, PostMortem
from incident_agent.memory.hindsight import IncidentMemory
from incident_agent.memory.schema import stack_trace_hash,format_postmortem,tags_for,metadata_for
from incident_agent.main import create_app

ROOT=Path(__file__).resolve().parents[1]
def fixtures():
    return json.loads((ROOT/"fixtures/incidents/incidents.json").read_text()),yaml.safe_load((ROOT/"fixtures/postmortems/postmortems.yaml").read_text())

@pytest.mark.asyncio
async def test_recall_upsert_scope_and_facts():
    alerts,pms=fixtures()
    memory=IncidentMemory(Settings(remote_memory=False))
    alert=Alert.model_validate(alerts[4])
    assert await memory.recall_for_alert(alert)==[]
    for pm in pms:
        await memory.retain(pm)
    await memory.retain(pms[0])
    assert len(memory.documents)==3
    result=await memory.recall_for_alert(alert)
    assert len(result)==3
    assert result[0]["document_id"]=="pm-INC-4401"
    assert result[0]["scores"]["reranker"]==0.71
    assert all("service:checkout-api" in m["tags"] for m in result)
    assert not await memory.recall_for_alert(alert.model_copy(update={"environment":"staging"}))
    assert (await memory.reflect())["patterns"]
    assert len(memory.query(alert))<=1800

@pytest.mark.asyncio
async def test_remote_contract_and_offline_failover():
    alerts,pms=fixtures()
    class Remote:
        def retain(self,**kwargs):
            self.retained=kwargs
            return {"success":True}
        def recall(self,**kwargs):
            self.recalled=kwargs
            raise ConnectionError("offline")
    remote=Remote()
    memory=IncidentMemory(Settings(),remote)
    await memory.retain(pms[0])
    result=await memory.recall_for_alert(Alert.model_validate(alerts[4]))
    assert result and memory.backend=="local-simulation"
    assert remote.retained["document_id"]=="pm-INC-4401"
    assert remote.retained["timestamp"].isoformat().startswith("2026-08-14")
    assert remote.recalled["types"]==["world","observation"]
    assert remote.recalled["prefer_observations"] is True
    assert remote.recalled["min_scores"]=={"reranker":0.35}
    assert remote.recalled["tag_groups"]

def test_canonicalization_and_metadata():
    assert stack_trace_hash(["at /app/src/Foo.java:12 0x123 request_id=abc"])==stack_trace_hash(["at /other/src/Foo.java:99 0x456 request_id=xyz"])
    pm=PostMortem.model_validate(fixtures()[1][0])
    assert "Incident INC-4401" in format_postmortem(pm)
    assert "verified_by" in metadata_for(pm)
    assert not any("verified_by" in tag for tag in tags_for(pm))

def test_end_to_end(tmp_path):
    cfg=Settings(fixtures_dir=ROOT/"fixtures",data_dir=tmp_path,groq_api_key="",remote_memory=False)
    with TestClient(create_app(cfg)) as client:
        assert client.get("/").status_code==200
        assert client.get("/healthz").json()["status"]=="ok"
        cold=client.post("/api/demo/cold").json()
        assert cold["phase"]=="awaiting_approval" and cold["memory_cold"]
        assert client.post("/api/demo/seed").json()["count"]==3
        warm=client.post("/api/demo/warm").json()
        assert warm["phase"]=="resolved"
        assert warm["verification"]["passed"] and len(warm["verification"]["samples"])==4
        assert warm["tool_calls"]<=12 and warm["band_output"]["tool"]=="band_send_message"
        assert len(warm["plan"]["evidence_ids"])==3
        rows=client.post("/api/demo/eval").json()["turns"]
        assert len(rows)==10 and rows[0]["facts_used"]==0 and rows[-1]["facts_used"]==3
        assert (tmp_path/"eval.jsonl").exists()
        alert=fixtures()[0][4]
        first=client.post("/webhook/alert",json=alert).json()
        assert first["incident"]["phase"]=="awaiting_approval"
        assert client.post("/webhook/alert",json=alert).json()["deduplicated"]
        job=client.post("/api/postmortems",json=fixtures()[1][0]).json()["job_id"]
        assert client.get("/api/postmortems/jobs/"+job).json()["status"]=="completed"
        assert client.post("/reflect",json={}).status_code==200
        assert "incident_runs_total" in client.get("/metrics").text

def test_auth_and_disabled_demo(tmp_path):
    with TestClient(create_app(Settings(api_token="test-secret",demo_enabled=False,fixtures_dir=ROOT/"fixtures",data_dir=tmp_path))) as client:
        assert client.post("/api/demo/seed").status_code==401
        assert client.post("/api/demo/seed",headers={"Authorization":"Bearer test-secret"}).status_code==404
