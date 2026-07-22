from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agent import SecurityAgent
from app.config import settings
from app.models import JobCreate
from app.policy import Policy, PolicyError
from app.store import Store


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

store = Store(settings.database_path)
store.initialize()
policy = Policy(settings)
agent = SecurityAgent(store=store, config=settings)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_tasks: set[asyncio.Task[None]] = set()


def serialize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


async def execute_job(job_id: str) -> None:
    await asyncio.to_thread(agent.run, job_id)


def spawn_job(job_id: str) -> None:
    task = asyncio.create_task(execute_job(job_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.openai_model}


@app.post("/api/jobs", status_code=202)
def create_job(payload: JobCreate) -> dict[str, Any]:
    try:
        policy.validate_target(payload.target)
    except PolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    max_steps = min(payload.max_steps, settings.max_max_steps)
    job = store.create_job(
        target=payload.target,
        objective=payload.objective,
        max_steps=max_steps,
    )
    spawn_job(job.id)
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
    }
