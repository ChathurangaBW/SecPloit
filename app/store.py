from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models import (
    Campaign,
    CampaignCreate,
    CampaignStatus,
    Event,
    Experiment,
    ExperimentCreate,
    ExperimentKind,
    ExperimentStatus,
    Finding,
    Job,
    JobStatus,
    new_id,
    utc_now,
)


class Store:
    def __init__(self, database_path: str) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    max_steps INTEGER NOT NULL,
                    current_step INTEGER NOT NULL DEFAULT 0,
                    workspace_id TEXT,
                    report TEXT,
                    error TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    step INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_job_created
                ON events(job_id, created_at);

                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    claim TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    remediation TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_findings_job
                ON findings(job_id, created_at);

                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    target TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    max_parallel INTEGER NOT NULL,
                    max_experiments INTEGER NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_campaigns_status_updated
                ON campaigns(status, updated_at);

                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    status TEXT NOT NULL,
                    parent_ids TEXT NOT NULL,
                    required_capabilities TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    checkpoint TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    result TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_experiments_campaign_status_priority
                ON experiments(campaign_id, status, priority DESC, created_at ASC);

                CREATE INDEX IF NOT EXISTS idx_experiments_lease
                ON experiments(status, lease_expires_at);
                """
            )

    def create_job(self, target: str, objective: str, max_steps: int) -> Job:
        now = utc_now()
        job = Job(
            id=new_id("job"),
            target=target,
            objective=objective,
            status=JobStatus.queued,
            max_steps=max_steps,
            created_at=now,
            updated_at=now,
        )
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO jobs (
                    id, target, objective, status, max_steps, current_step,
                    workspace_id, report, error, cancel_requested, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.target,
                    job.objective,
                    job.status.value,
                    job.max_steps,
                    job.current_step,
                    None,
                    None,
                    None,
                    0,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def list_jobs(self, limit: int = 100) -> list[Job]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._job(row) for row in rows]

    def update_job(self, job_id: str, **fields: Any) -> Job:
        allowed = {
            "status",
            "current_step",
            "workspace_id",
            "report",
            "error",
            "cancel_requested",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unsupported job fields: {sorted(unknown)}")

        normalized: dict[str, Any] = {}
        for key, value in fields.items():
            if isinstance(value, JobStatus):
                value = value.value
            if key == "cancel_requested":
                value = int(bool(value))
            normalized[key] = value
        normalized["updated_at"] = utc_now().isoformat()

        assignments = ", ".join(f"{key} = ?" for key in normalized)
        values = list(normalized.values()) + [job_id]
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)

        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def request_cancel(self, job_id: str) -> Job:
        return self.update_job(job_id, cancel_requested=True)

    def add_event(
        self,
        job_id: str,
        step: int,
        kind: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            id=new_id("evt"),
            job_id=job_id,
            step=step,
            kind=kind,
            message=message,
            data=data or {},
            created_at=utc_now(),
        )
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO events (id, job_id, step, kind, message, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.job_id,
                    event.step,
                    event.kind,
                    event.message,
                    json.dumps(event.data, ensure_ascii=False),
                    event.created_at.isoformat(),
                ),
            )
        return event

    def get_events(self, job_id: str, limit: int = 1000) -> list[Event]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM events
                WHERE job_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (job_id, limit),
            ).fetchall()
        return [self._event(row) for row in rows]

    def add_finding(
        self,
        job_id: str,
        title: str,
        severity: str,
        confidence: float,
        claim: str,
        evidence: str,
        remediation: str | None,
    ) -> Finding:
        finding = Finding(
            id=new_id("finding"),
            job_id=job_id,
            title=title,
            severity=severity,
            confidence=confidence,
            claim=claim,
            evidence=evidence,
            remediation=remediation,
            created_at=utc_now(),
        )
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO findings (
                    id, job_id, title, severity, confidence,
                    claim, evidence, remediation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding.id,
                    finding.job_id,
                    finding.title,
                    finding.severity,
                    finding.confidence,
                    finding.claim,
                    finding.evidence,
                    finding.remediation,
                    finding.created_at.isoformat(),
                ),
            )
        return finding

    def get_findings(self, job_id: str) -> list[Finding]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM findings
                WHERE job_id = ?
                ORDER BY created_at ASC
                """,
                (job_id,),
            ).fetchall()
        return [self._finding(row) for row in rows]

    def create_campaign(self, payload: CampaignCreate) -> Campaign:
        now = utc_now()
        campaign = Campaign(
            id=new_id("campaign"),
            name=payload.name,
            target=payload.target,
            objective=payload.objective,
            status=CampaignStatus.draft,
            max_parallel=payload.max_parallel,
            max_experiments=payload.max_experiments,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO campaigns (
                    id, name, target, objective, status, max_parallel,
                    max_experiments, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign.id,
                    campaign.name,
                    campaign.target,
                    campaign.objective,
                    campaign.status.value,
                    campaign.max_parallel,
                    campaign.max_experiments,
                    json.dumps(campaign.metadata, ensure_ascii=False),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return campaign

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM campaigns WHERE id = ?",
                (campaign_id,),
            ).fetchone()
        return self._campaign(row) if row else None

    def list_campaigns(self, limit: int = 100) -> list[Campaign]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM campaigns ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._campaign(row) for row in rows]

    def update_campaign_status(
        self,
        campaign_id: str,
        status: CampaignStatus,
    ) -> Campaign:
        now = utc_now().isoformat()
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE campaigns SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, campaign_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(campaign_id)
        campaign = self.get_campaign(campaign_id)
        if campaign is None:
            raise KeyError(campaign_id)
        return campaign

    def create_experiment(
        self,
        campaign_id: str,
        payload: ExperimentCreate,
        status: ExperimentStatus,
    ) -> Experiment:
        now = utc_now()
        experiment = Experiment(
            id=new_id("exp"),
            campaign_id=campaign_id,
            title=payload.title,
            kind=payload.kind,
            objective=payload.objective,
            hypothesis=payload.hypothesis,
            status=status,
            parent_ids=payload.parent_ids,
            required_capabilities=payload.required_capabilities,
            priority=payload.priority,
            max_attempts=payload.max_attempts,
            attempt=0,
            checkpoint={},
            payload=payload.payload,
            result={},
            created_at=now,
            updated_at=now,
        )
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO experiments (
                    id, campaign_id, title, kind, objective, hypothesis, status,
                    parent_ids, required_capabilities, priority, max_attempts,
                    attempt, lease_owner, lease_expires_at, checkpoint, payload,
                    result, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment.id,
                    experiment.campaign_id,
                    experiment.title,
                    experiment.kind.value,
                    experiment.objective,
                    experiment.hypothesis,
                    experiment.status.value,
                    json.dumps(experiment.parent_ids),
                    json.dumps(experiment.required_capabilities),
                    experiment.priority,
                    experiment.max_attempts,
                    experiment.attempt,
                    None,
                    None,
                    "{}",
                    json.dumps(experiment.payload, ensure_ascii=False),
                    "{}",
                    None,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return experiment

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM experiments WHERE id = ?",
                (experiment_id,),
            ).fetchone()
        return self._experiment(row) if row else None

    def list_experiments(self, campaign_id: str) -> list[Experiment]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM experiments
                WHERE campaign_id = ?
                ORDER BY priority DESC, created_at ASC
                """,
                (campaign_id,),
            ).fetchall()
        return [self._experiment(row) for row in rows]

    def count_experiments(self, campaign_id: str) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM experiments WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return int(row["n"])

    def update_experiment(self, experiment_id: str, **fields: Any) -> Experiment:
        allowed = {
            "status",
            "attempt",
            "lease_owner",
            "lease_expires_at",
            "checkpoint",
            "result",
            "error",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unsupported experiment fields: {sorted(unknown)}")

        normalized: dict[str, Any] = {}
        for key, value in fields.items():
            if isinstance(value, ExperimentStatus):
                value = value.value
            elif isinstance(value, datetime):
                value = value.isoformat()
            elif key in {"checkpoint", "result"}:
                value = json.dumps(value or {}, ensure_ascii=False)
            normalized[key] = value
        normalized["updated_at"] = utc_now().isoformat()

        assignments = ", ".join(f"{key} = ?" for key in normalized)
        values = list(normalized.values()) + [experiment_id]
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE experiments SET {assignments} WHERE id = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(experiment_id)
        experiment = self.get_experiment(experiment_id)
        if experiment is None:
            raise KeyError(experiment_id)
        return experiment

    def campaign_status_counts(self, campaign_id: str) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT status, COUNT(*) AS n
                FROM experiments
                WHERE campaign_id = ?
                GROUP BY status
                """,
                (campaign_id,),
            ).fetchall()
        return {row["status"]: int(row["n"]) for row in rows}

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            target=row["target"],
            objective=row["objective"],
            status=JobStatus(row["status"]),
            max_steps=row["max_steps"],
            current_step=row["current_step"],
            workspace_id=row["workspace_id"],
            report=row["report"],
            error=row["error"],
            cancel_requested=bool(row["cancel_requested"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> Event:
        return Event(
            id=row["id"],
            job_id=row["job_id"],
            step=row["step"],
            kind=row["kind"],
            message=row["message"],
            data=json.loads(row["data"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _finding(row: sqlite3.Row) -> Finding:
        return Finding(
            id=row["id"],
            job_id=row["job_id"],
            title=row["title"],
            severity=row["severity"],
            confidence=row["confidence"],
            claim=row["claim"],
            evidence=row["evidence"],
            remediation=row["remediation"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _campaign(row: sqlite3.Row) -> Campaign:
        return Campaign(
            id=row["id"],
            name=row["name"],
            target=row["target"],
            objective=row["objective"],
            status=CampaignStatus(row["status"]),
            max_parallel=row["max_parallel"],
            max_experiments=row["max_experiments"],
            metadata=json.loads(row["metadata"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _experiment(row: sqlite3.Row) -> Experiment:
        lease_expires_at = (
            datetime.fromisoformat(row["lease_expires_at"])
            if row["lease_expires_at"]
            else None
        )
        return Experiment(
            id=row["id"],
            campaign_id=row["campaign_id"],
            title=row["title"],
            kind=ExperimentKind(row["kind"]),
            objective=row["objective"],
            hypothesis=row["hypothesis"],
            status=ExperimentStatus(row["status"]),
            parent_ids=json.loads(row["parent_ids"]),
            required_capabilities=json.loads(row["required_capabilities"]),
            priority=row["priority"],
            max_attempts=row["max_attempts"],
            attempt=row["attempt"],
            lease_owner=row["lease_owner"],
            lease_expires_at=lease_expires_at,
            checkpoint=json.loads(row["checkpoint"]),
            payload=json.loads(row["payload"]),
            result=json.loads(row["result"]),
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
