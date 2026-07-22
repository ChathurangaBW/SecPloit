from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class JobStatus(StrEnum):
    queued = "queued"
    planning = "planning"
    running = "running"
    reporting = "reporting"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class CampaignStatus(StrEnum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ExperimentStatus(StrEnum):
    blocked = "blocked"
    queued = "queued"
    leased = "leased"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ExperimentKind(StrEnum):
    reconnaissance = "reconnaissance"
    browser = "browser"
    source = "source"
    binary = "binary"
    fuzzing = "fuzzing"
    race = "race"
    cloud = "cloud"
    hardware = "hardware"
    validation = "validation"
    analysis = "analysis"


class JobCreate(BaseModel):
    target: str = Field(min_length=1, max_length=500)
    objective: str = Field(min_length=10, max_length=4000)
    max_steps: int = Field(default=20, ge=1, le=200)


class Job(BaseModel):
    id: str
    target: str
    objective: str
    status: JobStatus
    max_steps: int
    current_step: int = 0
    workspace_id: str | None = None
    report: str | None = None
    error: str | None = None
    cancel_requested: bool = False
    created_at: datetime
    updated_at: datetime


class Event(BaseModel):
    id: str
    job_id: str
    step: int
    kind: str
    message: str
    data: dict[str, Any]
    created_at: datetime


class Finding(BaseModel):
    id: str
    job_id: str
    title: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    claim: str
    evidence: str
    remediation: str | None = None
    created_at: datetime


class Hypothesis(BaseModel):
    statement: str
    rationale: str
    priority: Literal["low", "medium", "high"] = "medium"


class SpecialistAssessment(BaseModel):
    role: str
    summary: str
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=10)
    recommended_actions: list[str] = Field(default_factory=list, max_length=10)
    evidence_requirements: list[str] = Field(default_factory=list, max_length=10)
    caveats: list[str] = Field(default_factory=list, max_length=8)


class ResearchPlan(BaseModel):
    summary: str
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=12)
    initial_commands: list[str] = Field(default_factory=list, max_length=8)
    completion_criteria: list[str] = Field(default_factory=list, max_length=10)


class OperatorDecision(BaseModel):
    action: Literal["run", "finish"]
    command: str = ""
    rationale: str
    expected_signal: str = ""
    report: str = ""


class ReviewedFinding(BaseModel):
    title: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    claim: str
    evidence: str
    remediation: str = ""


class StepReview(BaseModel):
    summary: str
    findings: list[ReviewedFinding] = Field(default_factory=list, max_length=10)
    next_focus: str
    should_stop: bool = False


class ReportAudit(BaseModel):
    summary: str
    accepted_finding_titles: list[str] = Field(default_factory=list, max_length=50)
    rejected_finding_titles: list[str] = Field(default_factory=list, max_length=50)
    material_caveats: list[str] = Field(default_factory=list, max_length=20)


class CampaignCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    target: str = Field(min_length=1, max_length=500)
    objective: str = Field(min_length=10, max_length=8000)
    max_parallel: int = Field(default=4, ge=1, le=64)
    max_experiments: int = Field(default=500, ge=1, le=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Campaign(BaseModel):
    id: str
    name: str
    target: str
    objective: str
    status: CampaignStatus
    max_parallel: int
    max_experiments: int
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ExperimentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    kind: ExperimentKind = ExperimentKind.analysis
    objective: str = Field(min_length=10, max_length=8000)
    hypothesis: str = Field(default="", max_length=8000)
    parent_ids: list[str] = Field(default_factory=list, max_length=64)
    required_capabilities: list[str] = Field(default_factory=list, max_length=64)
    priority: int = Field(default=50, ge=0, le=1000)
    max_attempts: int = Field(default=3, ge=1, le=20)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_dependencies(self) -> "ExperimentCreate":
        if len(self.parent_ids) != len(set(self.parent_ids)):
            raise ValueError("parent_ids must be unique")
        return self


class Experiment(BaseModel):
    id: str
    campaign_id: str
    title: str
    kind: ExperimentKind
    objective: str
    hypothesis: str
    status: ExperimentStatus
    parent_ids: list[str]
    required_capabilities: list[str]
    priority: int
    max_attempts: int
    attempt: int
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ExperimentLeaseRequest(BaseModel):
    worker_id: str = Field(min_length=3, max_length=200)
    capabilities: list[str] = Field(default_factory=list, max_length=128)
    lease_seconds: int = Field(default=300, ge=30, le=86400)


class ExperimentHeartbeat(BaseModel):
    worker_id: str = Field(min_length=3, max_length=200)
    lease_seconds: int = Field(default=300, ge=30, le=86400)
    checkpoint: dict[str, Any] = Field(default_factory=dict)


class ExperimentComplete(BaseModel):
    worker_id: str = Field(min_length=3, max_length=200)
    result: dict[str, Any] = Field(default_factory=dict)
    checkpoint: dict[str, Any] = Field(default_factory=dict)


class ExperimentFail(BaseModel):
    worker_id: str = Field(min_length=3, max_length=200)
    error: str = Field(min_length=1, max_length=12000)
    retryable: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    checkpoint: dict[str, Any] = Field(default_factory=dict)


class GroundTruthFinding(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    severity: Literal["info", "low", "medium", "high", "critical"]
    aliases: list[str] = Field(default_factory=list, max_length=20)


class EvaluationInput(BaseModel):
    expected: list[GroundTruthFinding]
    observed: list[ReviewedFinding]
