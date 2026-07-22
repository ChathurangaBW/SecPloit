from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


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
