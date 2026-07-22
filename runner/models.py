from __future__ import annotations

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    job_id: str = Field(pattern=r"^job_[a-f0-9]{32}$")


class ExecRequest(BaseModel):
    command: str = Field(min_length=1, max_length=12000)
    timeout_seconds: int = Field(default=180, ge=1, le=1800)
    max_output_bytes: int = Field(default=120000, ge=4096, le=2_000_000)
