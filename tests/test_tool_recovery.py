from types import SimpleNamespace as NS
import pytest
from incident_agent.config import Settings
from incident_agent.llm.groq_client import GroqAgent
from incident_agent.llm.tool_loop import run_incident
from incident_agent.llm.tools import ToolCall,dispatch
from incident_agent.state import IncidentState
from incident_agent.models import Alert
from incident_agent.memory.hindsight import IncidentMemory
from incident_agent.execution.runbook_runner import Sandbox
from test_recall_quality import fixtures

class Failure(Exception):
    def __init__(self,status,body=None):
        self.status_code=status
        self.body=body or {}
        self.response=NS(headers={"retry-after":"0"})

def response(name="k8s_logs",args="{}",content=None):
    return NS(usage=NS(total_tokens=7),choices=[NS(message=NS(content=content,tool_calls=[] if content else [NS(id="call-1",function=NS(name=name,arguments=args))]))])

class FakeClient:
    def __init__(self,outcomes):
        self.outcomes=iter(outcomes)
        self.calls=[]
        self.chat=NS(completions=self)
    async def create(self,**kwargs):
        self.calls.append({**kwargs,"messages":list(kwargs["messages"])})
        result=next(self.outcomes)
        if isinstance(result,Exception):
            raise result
        return result

def state():
    return IncidentState(Alert.model_validate(fixtures()[0][0]))

@pytest.mark.asyncio
async def test_rate_limit_failover():
    client=FakeClient([Failure(429),Failure(429),response()])
    agent=GroqAgent(Settings(max_backoff=0),client)
    assert (await agent.step(state())).name=="k8s_logs"
    assert client.calls[-1]["model"]==agent.cfg.fallback_model
    assert all(c["parallel_tool_calls"] is False for c in client.calls)

@pytest.mark.asyncio
async def test_tool_use_repair():
    client=FakeClient([Failure(400,{"error":{"code":"tool_use_failed"}}),response()])
    agent=GroqAgent(Settings(),client)
    assert (await agent.step(state())).name=="k8s_logs"
    assert any("Repair" in m.get("content","") for m in agent.messages)

@pytest.mark.asyncio
async def test_json_degradation_has_no_mutations():
    client=FakeClient([Failure(503),Failure(503),Failure(503),response(content='{"summary":"Inspect metrics and page on-call"}')])
    agent=GroqAgent(Settings(max_backoff=0),client)
    assert (await agent.step(state())).name=="page_oncall"
    assert agent.degraded
    assert client.calls[-1]["response_format"]=={"type":"json_object"}
    assert "tools" not in client.calls[-1]

@pytest.mark.asyncio
async def test_invalid_tool_repairs_and_token_accounting():
    client=FakeClient([response("shell"),response()])
    agent=GroqAgent(Settings(),client)
    st=state()
    assert (await agent.step(st)).name=="k8s_logs"
    assert st.token_count==14

@pytest.mark.asyncio
async def test_budget_and_band_conclusion():
    class Endless:
        model_id="test"
        async def step(self,state):
            return ToolCall(name="k8s_logs")
        def record_tool_result(self,result):
            self.last_result=result
    cfg=Settings(max_tool_calls=12)
    result=await run_incident(state().alert,IncidentMemory(cfg),Endless(),cfg)
    assert result.tool_calls==12
    assert result.band_output["tool"]=="band_send_message"
    assert result.phase.value=="escalated"

@pytest.mark.asyncio
async def test_unknown_or_injected_arguments_rejected():
    st=state()
    with pytest.raises(ValueError):
        await dispatch(ToolCall(name="k8s_logs",arguments={"command":"delete namespace"}),st,Sandbox(st.alert),Settings())
    assert st.tool_calls==0
