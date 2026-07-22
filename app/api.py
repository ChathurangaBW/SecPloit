from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.models import JobCreate
from app.orchestrator import Orchestrator
from app.policy import Policy, PolicyError
from app.runner_client import RunnerClient
from app.store import Store


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

store = Store(settings.database_path)
store.initialize()
policy = Policy(settings)
runner = RunnerClient(settings)
orchestrator = Orchestrator(store=store, config=settings, runner=runner, policy=policy)

app = FastAPI(title=settings.app_name, version="2.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
_tasks: set[asyncio.Task[None]] = set()


def serialize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


async def run_job(job_id: str) -> None:
    await asyncio.to_thread(orchestrator.run, job_id)


def spawn(job_id: str) -> None:
    task = asyncio.create_task(run_job(job_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": "2.0.0",
        "model": settings.openai_model,
        "runner": settings.runner_url,
    }


@app.post("/api/jobs", status_code=202)
def create_job(payload: JobCreate) -> dict[str, Any]:
    try:
        policy.validate_target(payload.target)
    except PolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    max_steps = min(payload.max_steps, settings.max_steps)
    job = store.create_job(payload.target, payload.objective, max_steps)
    store.add_event(job.id, 0, "status", "Engagement queued")
    spawn(job.id)
    return {"job": serialize(job)}


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": [serialize(job) for job in store.list_jobs()]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job": serialize(job),
        "events": [serialize(event) for event in store.get_events(job_id)],
        "findings": [serialize(item) for item in store.get_findings(job_id)],
    }


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    if store.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    orchestrator.cancel(job_id)
    return {"job": serialize(store.get_job(job_id))}


@app.get("/api/jobs/{job_id}/artifacts")
def list_artifacts(job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.workspace_id:
        return {"artifacts": []}
    try:
        return {"artifacts": runner.list_artifacts(job.workspace_id)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Runner error: {exc}") from exc
