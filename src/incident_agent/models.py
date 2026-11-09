from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Alert(StrictModel):
    incident_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    service: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    environment: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    severity: Literal["p1", "p2", "p3"] = "p1"
    error_class: str = Field(max_length=200)
    error_code: str = Field(max_length=200)
    message: str = Field(max_length=4000)
    symptom: str = Field(max_length=2000)
    top_frames: list[str] = Field(default_factory=list, max_length=30)
    version: str = Field(default="", max_length=80)
    @field_validator("top_frames")
    @classmethod
    def bounded_frames(cls, frames):
        if any(len(f)>1000 for f in frames):
            raise ValueError("Stack frames must be at most 1000 characters")
        return frames

class Hypothesis(StrictModel):
    cause: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)

class Plan(StrictModel):
    summary: str
    runbook_id: str = ""
    steps: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    requires_approval: bool = True

class PostMortem(StrictModel):
    incident_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    service: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    environment: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    severity: Literal["p1", "p2", "p3"]
    error_class: str
    error_code: str
    started_at: datetime
    resolved_at: datetime
    valid_until: datetime
    top_frames: list[str]
    root_cause: str
    root_cause_slug: str = Field(pattern=r"^[a-z0-9-]+$")
    trigger: str
    alert_signature: str
    impact: str
    failed_attempts: str
    resolution_steps: list[str]
    verification: str
    prevention: str
    resolution_status: Literal["verified", "partial", "deprecated"]
    verified_by: str = ""
    mttr_minutes: float = Field(ge=0)
    author: str
    runbook_id: str
    pr_url: str = ""
    @field_validator("started_at", "resolved_at", "valid_until")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamps must include a timezone")
        return value

class EvalTurn(StrictModel):
    turn: int
    bank_size: int
    recall_fact_count: int
    top_reranker_score: float
    facts_used: int
    mttr_minutes: float
    measured_latency_ms: float
    mttr_kind: str = "projected_simulation"
    precision_at_1: float
