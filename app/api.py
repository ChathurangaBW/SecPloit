from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.campaigns import CampaignError, CampaignService, LeaseConflict
from app.config import settings
from app.evaluation import score_ground_truth
from app.models import (
    CampaignCreate,
    EvaluationInput,
    ExperimentComplete,
    ExperimentCreate,
    ExperimentFail,
    ExperimentHeartbeat,
    ExperimentLeaseRequest,
    JobCreate,
)
from app.orchestrator import Orchestrator, SCOUT_PROFILES
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
campaigns = CampaignService(store)

app = FastAPI(title=settings.app_name, version="4.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
_tasks: set[asyncio.Task[None]] = set()


def serialize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    return value


def campaign_call(function, *args):
    try:
        return function(*args)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Campaign or experiment not found") from exc
    except LeaseConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CampaignError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        "version": "4.0.0",
        "model": settings.openai_model,
        "critic_model": settings.critic_model,
        "reasoning_mode": settings.openai_reasoning_mode,
        "reasoning_effort": settings.openai_reasoning_effort,
        "operator_reasoning_effort": settings.openai_operator_reasoning_effort,
        "critic_reasoning_effort": settings.openai_critic_reasoning_effort,
        "planning_agents": settings.planning_agents,
        "runner": settings.runner_url,
        "campaign_engine": True,
    }


@app.get("/api/capabilities")
def capabilities() -> dict[str, Any]:
    active_profiles = SCOUT_PROFILES[: settings.planning_agents]
    return {
        "version": "4.0.0",
        "workflow": [
            "parallel_specialists",
            "lead_planner",
            "operator",
            "step_reviewer",
            "final_evidence_auditor",
            "reporter",
            "durable_campaign_graph",
            "distributed_worker_leases",
            "checkpointed_experiments",
            "ground_truth_scoring",
        ],
        "specialists": [role for role, _ in active_profiles],
        "reasoning": {
            "mode": settings.openai_reasoning_mode,
            "planner_and_specialists": settings.openai_reasoning_effort,
            "operator": settings.openai_operator_reasoning_effort,
            "reviewer_auditor_reporter": settings.openai_critic_reasoning_effort,
            "max_output_tokens": settings.openai_max_output_tokens,
            "store_responses": settings.openai_store_responses,
        },
        "workspace": {
            "persistent_per_engagement": True,
            "public_egress": False,
            "host_path_mounts": False,
            "browser_evidence": True,
            "general_shell": True,
        },
        "campaigns": {
            "dependency_graph": True,
            "resumable_checkpoints": True,
            "worker_capability_routing": True,
            "lease_expiry_recovery": True,
            "bounded_parallelism": True,
        },
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


@app.post("/api/campaigns", status_code=201)
def create_campaign(payload: CampaignCreate) -> dict[str, Any]:
    try:
        policy.validate_target(payload.target)
    except PolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"campaign": serialize(campaigns.create_campaign(payload))}


@app.get("/api/campaigns")
def list_campaigns() -> dict[str, Any]:
    return {"campaigns": serialize(store.list_campaigns())}


@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict[str, Any]:
    return serialize(campaign_call(campaigns.summary, campaign_id))


@app.get("/api/campaigns/{campaign_id}/graph")
def get_campaign_graph(campaign_id: str) -> dict[str, Any]:
    return serialize(campaign_call(campaigns.graph, campaign_id))


@app.post("/api/campaigns/{campaign_id}/activate")
def activate_campaign(campaign_id: str) -> dict[str, Any]:
    return {"campaign": serialize(campaign_call(campaigns.activate, campaign_id))}


@app.post("/api/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str) -> dict[str, Any]:
    return {"campaign": serialize(campaign_call(campaigns.pause, campaign_id))}


@app.post("/api/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: str) -> dict[str, Any]:
    return {"campaign": serialize(campaign_call(campaigns.cancel, campaign_id))}


@app.post("/api/campaigns/{campaign_id}/experiments", status_code=201)
def create_experiment(campaign_id: str, payload: ExperimentCreate) -> dict[str, Any]:
    experiment = campaign_call(campaigns.add_experiment, campaign_id, payload)
    return {"experiment": serialize(experiment)}


@app.post("/api/campaigns/{campaign_id}/lease")
def lease_experiment(
    campaign_id: str,
    payload: ExperimentLeaseRequest,
) -> dict[str, Any]:
    experiment = campaign_call(campaigns.lease_next, campaign_id, payload)
    return {"experiment": serialize(experiment) if experiment else None}


@app.post("/api/experiments/{experiment_id}/heartbeat")
def heartbeat_experiment(
    experiment_id: str,
    payload: ExperimentHeartbeat,
) -> dict[str, Any]:
    return {
        "experiment": serialize(
            campaign_call(campaigns.heartbeat, experiment_id, payload)
        )
    }


@app.post("/api/experiments/{experiment_id}/complete")
def complete_experiment(
    experiment_id: str,
    payload: ExperimentComplete,
) -> dict[str, Any]:
    return {
        "experiment": serialize(
            campaign_call(campaigns.complete, experiment_id, payload)
        )
    }


@app.post("/api/experiments/{experiment_id}/fail")
def fail_experiment(
    experiment_id: str,
    payload: ExperimentFail,
) -> dict[str, Any]:
    return {
        "experiment": serialize(
            campaign_call(campaigns.fail, experiment_id, payload)
        )
    }


@app.post("/api/evaluations/ground-truth")
def evaluate_ground_truth(payload: EvaluationInput) -> dict[str, Any]:
    return score_ground_truth(payload)
