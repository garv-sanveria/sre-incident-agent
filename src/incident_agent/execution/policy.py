from ..memory.freshness import is_usable

RUNBOOKS={
    "RB-CHECKOUT-OOM":{"service":"checkout-api","error":"OOMKilled","version":"v2.14","steps":["rollback-v2.13.7","flush-pricing-cache"]},
    "RB-ORDERS-POOL":{"service":"orders-api","error":"POOL_EXHAUSTED","version":"v3.3.0","steps":["rollback-v3.2.1","drain-connections"]},
    "RB-SESSION-EVICT":{"service":"session-svc","error":"REDIS_EVICTED","version":"shared-cache","steps":["protect-session-keys","isolate-analytics"]},
}

def eligible(memory, alert, floor):
    tags=memory.get("tags",[])
    return is_usable(memory) and all(t in tags for t in ["status:verified",f"service:{alert.service}",
        f"env:{alert.environment}",f"error:{alert.error_code}"]) and bool(memory.get("metadata",{}).get("verified_by","")) and memory.get("scores",{}).get("reranker",0)>=floor

def conflicting_fixes(memories, alert, floor):
    fixes=set()
    causes=set()
    for memory in memories[:9]:
        if eligible(memory,alert,floor):
            fixes.add(memory["metadata"].get("runbook_id",""))
            causes.add(memory["metadata"].get("root_cause",""))
    return len(fixes)>1 or len(causes)>1

def fast_path_confident(memories, alert, floor):
    if conflicting_fixes(memories,alert,floor):
        return False
    return any(eligible(m,alert,floor) and m["metadata"].get("runbook_id") in RUNBOOKS and
        RUNBOOKS[m["metadata"]["runbook_id"]]["version"]==alert.version for m in memories[:3])

def authorize_step(state, runbook_id, step, floor):
    rb=RUNBOOKS.get(runbook_id)
    if not rb or rb["service"]!=state.alert.service or rb["error"]!=state.alert.error_code or step not in rb["steps"]:
        return False
    return not state.conflict and fast_path_confident(state.memories,state.alert,floor) and any(
        eligible(m,state.alert,floor) and m["metadata"].get("runbook_id")==runbook_id for m in state.memories[:3])
