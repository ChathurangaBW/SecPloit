from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models import Event, Finding, Job, JobStatus, new_id, utc_now


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
