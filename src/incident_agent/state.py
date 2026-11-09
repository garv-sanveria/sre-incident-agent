from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timezone
from time import perf_counter
from .models import Alert

class Phase(str, Enum):
    INGESTED="ingested"
    RECALLED="recalled"
    DIAGNOSED="diagnosed"
    AWAITING_APPROVAL="awaiting_approval"
    EXECUTING="executing"
    VERIFIED="verified"
    RESOLVED="resolved"
    ESCALATED="escalated"

@dataclass
class IncidentState:
    alert: Alert
    phase: Phase = Phase.INGESTED
    memories: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    executed_steps: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    hypotheses: list = field(default_factory=list)
    tool_calls: int = 0
    max_tool_calls: int = 12
    memory_cold: bool = True
    conflict: bool = False
    simulation: bool = True
    model_id: str = "deterministic-offline"
    token_count: int = 0
    phase_latency_ms: dict = field(default_factory=dict)
    projected_mttr_minutes: float = 42
    band_output: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    last_mark: float = field(default_factory=perf_counter)
    def mark(self, phase, note=""):
        now=perf_counter()
        self.phase_latency_ms[self.phase.value]=self.phase_latency_ms.get(self.phase.value,0)+(now-self.last_mark)*1000
        self.last_mark=now
        self.phase=phase
        self.timeline.append({"t":datetime.now(timezone.utc).isoformat(),"phase":phase.value,"note":note})
    def consume(self, name, args):
        if self.tool_calls >= self.max_tool_calls:
            raise RuntimeError("Tool budget exhausted")
        self.tool_calls+=1
        self.executed_steps.append({"tool":name,"args":args,"ok":False})
    def public(self):
        result=asdict(self)
        result.pop("last_mark")
        result["alert"]=self.alert.model_dump()
        result["phase"]=self.phase.value
        result["confidence_gate"]="memory_cold" if self.memory_cold else "FAST_PATH_VERIFIED"
        return result
