from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException

from runner.docker_backend import DockerWorkspaceBackend
from runner.models import ExecRequest, WorkspaceCreate

TOKEN = os.getenv("SECPLOIT_RUNNER_TOKEN", "change-this-runner-token")
backend = DockerWorkspaceBackend()
app = FastAPI(title="SecPloit Runner", version="2.0.0")


def authenticate(authorization: str = Header(default="")) -> None:
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, TOKEN):
        raise HTTPException(status_code=401, detail="Invalid runner token")


@app.get("/health")
def health() -> dict[str, Any]:
    return backend.health()


@app.post("/v1/workspaces", dependencies=[Depends(authenticate)])
def create_workspace(payload: WorkspaceCreate) -> dict[str, Any]:
    try:
        return backend.create(payload.job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workspace creation failed: {exc}") from exc


@app.post("/v1/workspaces/{workspace_id}/exec", dependencies=[Depends(authenticate)])
def execute(workspace_id: str, payload: ExecRequest) -> dict[str, Any]:
    try:
        return backend.execute(
            workspace_id=workspace_id,
            command=payload.command,
            timeout_seconds=payload.timeout_seconds,
            max_output_bytes=payload.max_output_bytes,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}") from exc


@app.get("/v1/workspaces/{workspace_id}/artifacts", dependencies=[Depends(authenticate)])
def artifacts(workspace_id: str) -> dict[str, Any]:
    try:
        return {"artifacts": backend.artifacts(workspace_id)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Artifact listing failed: {exc}") from exc


@app.delete("/v1/workspaces/{workspace_id}", dependencies=[Depends(authenticate)])
def delete_workspace(workspace_id: str) -> dict[str, bool]:
    try:
        backend.delete(workspace_id)
        return {"deleted": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workspace deletion failed: {exc}") from exc
