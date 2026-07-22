from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.models import EventRecord, JobRecord, JobStatus


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    max_steps INTEGER NOT NULL,
                    current_step INTEGER NOT NULL DEFAULT 0,
                    report TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    step INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_events_job_id
                    ON events(job_id, id);
                """
            )

    def create_job(self, target: str, objective: str, max_steps: int) -> JobRecord:
        now = utc_now()
        job_id = uuid4().hex

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, target, objective, status, max_steps, current_step,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    job_id,
                    target,
                    objective,
                    JobStatus.queued.value,
                    max_steps,
                    now,
                    now,
                ),
            )

        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError("Failed to persist job")
        return job

    def update_job(self, job_id: str, **fields: Any) -> JobRecord:
        allowed = {
            "status",
            "current_step",
            "report",
            "error",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unsupported job fields: {sorted(unknown)}")

        values: dict[str, Any] = dict(fields)
        if isinstance(values.get("status"), JobStatus):
            values["status"] = values["status"].value
        values["updated_at"] = utc_now()

        assignments = ", ".join(f"{name} = ?" for name in values)
        parameters = [*values.values(), job_id]

        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                parameters,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown job: {job_id}")

        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError("Failed to reload updated job")
        return job

    def add_event(
        self,
        job_id: str,
        step: int,
        kind: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> EventRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO events (job_id, step, kind, message, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    step,
                    kind,
                    message,
                    json.dumps(data or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )
            event_id = int(cursor.lastrowid)

        events = self.get_events(job_id)
        event = next((item for item in events if item.id == event_id), None)
        if event is None:
            raise RuntimeError("Failed to persist event")
        return event

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()

        return JobRecord.model_validate(dict(row)) if row else None

    def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        return [JobRecord.model_validate(dict(row)) for row in rows]

    def get_events(self, job_id: str) -> list[EventRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE job_id = ? ORDER BY id ASC",
                (job_id,),
            ).fetchall()

        result: list[EventRecord] = []
        for row in rows:
            item = dict(row)
            item["data"] = json.loads(item["data"])
            result.append(EventRecord.model_validate(item))
        return result
