from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class JobCreate(BaseModel):
    target: str = Field(min_length=1, max_length=500)
    objective: str = Field(min_length=10, max_length=4_000)
    max_steps: int = Field(default=12, ge=1, le=40)

    @field_validator("target", "objective")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class JobRecord(BaseModel):
    id: str
    target: str
    objective: str
    status: JobStatus
    max_steps: int
    current_step: int = 0
    report: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class EventRecord(BaseModel):
    id: int
    job_id: str
    step: int
    kind: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
