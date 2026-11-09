import asyncio
import json
import logging
from .tools import ToolCall, ARGUMENTS, SCHEMAS
from .prompts import SYSTEM, evidence_prompt
from ..execution.policy import RUNBOOKS

log=logging.getLogger(__name__)

class GroqAgent:
    def __init__(self,cfg,client=None,sleep=asyncio.sleep):
        self.cfg=cfg
        self.client=client
        self.sleep=sleep
        self.messages=[]
        self.model_id=cfg.primary_model
        self.degraded=False
        self.last_error=""
        if client is None and cfg.groq_api_key:
            try:
                from groq import AsyncGroq
                self.client=AsyncGroq(api_key=cfg.groq_api_key,max_retries=0,timeout=cfg.request_timeout)
            except ImportError:
                log.warning("Groq SDK unavailable; deterministic triage enabled")
        if not self.client:
            self.model_id="deterministic-offline"
        log.info("Resolved model ID: %s (configured primary=%s fallback=%s)",self.model_id,cfg.primary_model,cfg.fallback_model)

    def deterministic(self,state):
        names=[s["tool"] for s in state.executed_steps if s["ok"]]
        for name in ["k8s_logs","metrics_query","git_diff"]:
            if name not in names:
                return ToolCall(name=name)
        if not state.memory_cold and not self.degraded:
            for step in state.plan.get("steps",[]):
                if not any(s["ok"] and s["args"].get("step")==step for s in state.executed_steps):
                    return ToolCall(name="run_runbook_step",arguments={"runbook_id":state.plan["runbook_id"],"step":step})
        return ToolCall(name="band_send_message",arguments={"message":state.plan.get("summary","Human triage required")})

    async def _create(self,json_mode=False):
        kwargs={"model":self.model_id,"messages":self.messages,"temperature":0.1,"max_completion_tokens":1200}
        if json_mode:
            kwargs["response_format"]={"type":"json_object"}
        else:
            kwargs.update(tools=SCHEMAS,tool_choice="auto",parallel_tool_calls=False)
        return await self.client.chat.completions.create(**kwargs)

    def _parse(self,response,state):
        usage=getattr(response,"usage",None)
        state.token_count+=getattr(usage,"total_tokens",0) or 0
        message=response.choices[0].message
        calls=message.tool_calls or []
        if len(calls)>1:
            raise ValueError("Exactly one tool call per turn is supported")
        if not calls:
            return ToolCall(name="band_send_message",arguments={"message":message.content or "Human review requested"})
        call=calls[0]
        if call.function.name not in ARGUMENTS:
            raise ValueError("Unknown tool")
        args=json.loads(call.function.arguments)
        args=ARGUMENTS[call.function.name].model_validate(args).model_dump()
        self.messages.append({"role":"assistant","tool_calls":[{"id":call.id,"type":"function","function":{"name":call.function.name,"arguments":json.dumps(args)}}]})
        return ToolCall(name=call.function.name,arguments=args)

    def record_tool_result(self,result):
        if self.messages and self.messages[-1].get("tool_calls"):
            call=self.messages[-1]["tool_calls"][0]
            self.messages.append({"role":"tool","tool_call_id":call["id"],"content":json.dumps(result)})

    async def step(self,state):
        if not self.client or self.degraded:
            return self.deterministic(state)
        if not self.messages:
            self.messages=[{"role":"system","content":SYSTEM},{"role":"user","content":
                json.dumps({"alert":state.alert.model_dump(),"server_plan":state.plan})+evidence_prompt(state)}]
        for attempt in range(self.cfg.retry_limit):
            self.model_id=self.cfg.primary_model if attempt<2 else self.cfg.fallback_model
            try:
                return self._parse(await self._create(),state)
            except Exception as exc:
                self.last_error=type(exc).__name__
                status=getattr(exc,"status_code",None)
                body=getattr(exc,"body",{}) or {}
                err=body.get("error",body) if isinstance(body,dict) else {}
                if isinstance(err,dict) and err.get("code")=="tool_use_failed" or isinstance(exc,(ValueError,TypeError)):
                    self.messages.append({"role":"system","content":"Repair the rejected call. Emit exactly one known tool with valid JSON arguments conforming to its schema."})
                    continue
                if status==429 or status in (500,502,503,504) or status is None:
                    headers=getattr(getattr(exc,"response",None),"headers",{})
                    try:
                        delay=float(headers.get("retry-after",2**attempt))
                    except (TypeError,ValueError):
                        delay=2**attempt
                    await self.sleep(max(0,min(delay,self.cfg.max_backoff)))
                    continue
                break
        self.degraded=True
        self.model_id=self.cfg.fallback_model
        self.messages.append({"role":"system","content":"Return a JSON object with a summary of safe read-only triage. No executable calls."})
        try:
            response=await self._create(json_mode=True)
            state.token_count+=getattr(getattr(response,"usage",None),"total_tokens",0) or 0
            data=json.loads(response.choices[0].message.content)
            return ToolCall(name="page_oncall",arguments={"message":str(data.get("summary","Model degraded: human triage required"))[:4000]})
        except Exception:
            self.model_id="deterministic-offline"
            return ToolCall(name="page_oncall",arguments={"message":"Inference unavailable. Inspect pod logs, deployment diff, memory and pool pressure; human approval required."})
