import json
import logging

log=logging.getLogger("incident_agent.audit")
class Metrics:
    def __init__(self):
        self.runs=0
        self.tokens=0
        self.phase_ms={}
        self.resolved=0
    def record(self,state):
        self.runs+=1
        self.tokens+=state.token_count
        self.resolved+=int(state.phase.value=="resolved")
        for phase,ms in state.phase_latency_ms.items():
            self.phase_ms[phase]=self.phase_ms.get(phase,0)+ms
        log.info(json.dumps({"incident_id":state.alert.incident_id,"phase":state.phase.value,
            "tokens":state.token_count,"phase_latency_ms":state.phase_latency_ms,"tool_calls":state.tool_calls}))
    def prometheus(self):
        lines=["# TYPE incident_runs_total counter",f"incident_runs_total {self.runs}",
            "# TYPE incident_tokens_total counter",f"incident_tokens_total {self.tokens}",
            "# TYPE incident_simulated_resolutions_total counter",f"incident_simulated_resolutions_total {self.resolved}"]
        lines += [f'incident_phase_duration_seconds_sum{{phase="{phase}"}} {ms/1000}' for phase,ms in self.phase_ms.items()]
        return "\n".join(lines)+"\n"
