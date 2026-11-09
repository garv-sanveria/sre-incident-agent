"""Capability sandbox: immutable action catalog, no shell or model-authored commands."""
from .policy import RUNBOOKS, authorize_step

class Sandbox:
    def __init__(self, alert):
        self.alert=alert
        self.completed=[]
        self.tick=0
    def metrics(self):
        self.tick+=1
        fixed=any(rb["service"]==self.alert.service and set(rb["steps"])<=set(self.completed) for rb in RUNBOOKS.values())
        return {"source":"simulation","sample":self.tick,"memory_gib":0.8 if fixed else 1.98,
            "pool_utilization":0.34 if fixed else 1.0,"evictions_per_second":0 if fixed else 1200,
            "five_xx_burn":0.2 if fixed else 12,"restart_delta":0 if fixed else 2,"ready":fixed}
    def execute(self, state, runbook_id, step, floor):
        if not state.simulation:
            raise PermissionError("Live mutation disabled: no production actuator is configured")
        if not authorize_step(state,runbook_id,step,floor):
            raise PermissionError("Human review required: evidence or runbook scope does not authorize this action")
        required=RUNBOOKS[runbook_id]["steps"]
        index=required.index(step)
        if not all(s in self.completed for s in required[:index]):
            raise PermissionError("Runbook prerequisites not satisfied")
        if step not in self.completed:
            self.completed.append(step)
        return {"ok":True,"dry_run":True,"action":step,"scope":state.alert.service,"completed":list(self.completed)}
