import hashlib
import re
from ..models import PostMortem

def canonical_frames(frames):
    result=[]
    for frame in frames[:5]:
        frame=re.sub(r"\b\d{4}-\d\d-\d\d[T ][\d:.]+Z?", "", frame)
        frame=re.sub(r"0x[0-9a-fA-F]+|(?i:request[_-]?id|trace[_-]?id)[=: ]+[\w-]+", "", frame)
        frame=re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b", "", frame)
        frame=re.sub(r":\d+|\bline \d+\b", "", frame)
        frame=re.sub(r"(?:/[\w.-]+)+/", "", frame)
        result.append(" ".join(frame.split()))
    return result

def stack_trace_hash(frames):
    return "sha256:"+hashlib.sha256("\n".join(canonical_frames(frames)).encode()).hexdigest()

def tags_for(pm):
    return [f"service:{pm.service}",f"env:{pm.environment}",f"error:{pm.error_code}",
            f"cause:{pm.root_cause_slug}",f"severity:{pm.severity}",
            f"status:{pm.resolution_status}","kind:postmortem"]

def metadata_for(pm):
    keys=["incident_id","root_cause","runbook_id","pr_url","mttr_minutes","author","verified_by","valid_until"]
    data=pm.model_dump(mode="json")
    return {**{k:str(data[k]) for k in keys},"stack_trace_hash":stack_trace_hash(pm.top_frames)}

def facts_for(pm: PostMortem):
    subject=f"Incident {pm.incident_id} affected {pm.service} in {pm.environment}"
    return [f"{subject}; its root cause was {pm.root_cause}",
            f"{subject}; runbook {pm.runbook_id} resolved it using: {'; '.join(pm.resolution_steps)}.",
            f"{subject}; {pm.verified_by or pm.author} recorded verification: {pm.verification}"]

def format_postmortem(pm):
    facts=facts_for(pm)
    for label,value in [("started at",pm.started_at.isoformat()),("resolved at",pm.resolved_at.isoformat()),
        ("had impact",pm.impact),("had alert",pm.alert_signature),("had error class",pm.error_class),
        ("had error code",pm.error_code),("had frames",", ".join(canonical_frames(pm.top_frames))),
        ("was triggered by",pm.trigger),("had unsuccessful attempts",pm.failed_attempts),
        ("led to prevention",pm.prevention),("had resolution duration in minutes",pm.mttr_minutes)]:
        facts.append(f"Incident {pm.incident_id} {label} {value}.")
    return "\n".join(facts)
