from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from app.models import (
    Campaign,
    CampaignCreate,
    CampaignStatus,
    Experiment,
    ExperimentComplete,
    ExperimentCreate,
    ExperimentFail,
    ExperimentHeartbeat,
    ExperimentLeaseRequest,
    ExperimentStatus,
    utc_now,
)
from app.store import Store


class CampaignError(ValueError):
    pass


class LeaseConflict(CampaignError):
    pass


class CampaignService:
    """Durable experiment-graph scheduler for long-horizon research campaigns."""

    TERMINAL_EXPERIMENT_STATES = {
        ExperimentStatus.succeeded,
        ExperimentStatus.failed,
        ExperimentStatus.cancelled,
    }

    def __init__(self, store: Store) -> None:
        self.store = store

    def create_campaign(self, payload: CampaignCreate) -> Campaign:
        return self.store.create_campaign(payload)

    def activate(self, campaign_id: str) -> Campaign:
        campaign = self._campaign(campaign_id)
        if campaign.status not in {CampaignStatus.draft, CampaignStatus.paused}:
            raise CampaignError(f"Campaign cannot be activated from {campaign.status.value}")
        campaign = self.store.update_campaign_status(campaign_id, CampaignStatus.active)
        self.refresh(campaign_id)
        return campaign

    def pause(self, campaign_id: str) -> Campaign:
        campaign = self._campaign(campaign_id)
        if campaign.status != CampaignStatus.active:
            raise CampaignError("Only active campaigns can be paused")
        return self.store.update_campaign_status(campaign_id, CampaignStatus.paused)

    def cancel(self, campaign_id: str) -> Campaign:
        campaign = self._campaign(campaign_id)
        if campaign.status in {
            CampaignStatus.completed,
            CampaignStatus.failed,
            CampaignStatus.cancelled,
        }:
            return campaign
        for experiment in self.store.list_experiments(campaign_id):
            if experiment.status not in self.TERMINAL_EXPERIMENT_STATES:
                self.store.update_experiment(
                    experiment.id,
                    status=ExperimentStatus.cancelled,
                    lease_owner=None,
                    lease_expires_at=None,
                )
        return self.store.update_campaign_status(campaign_id, CampaignStatus.cancelled)

    def add_experiment(
        self,
        campaign_id: str,
        payload: ExperimentCreate,
    ) -> Experiment:
        campaign = self._campaign(campaign_id)
        if campaign.status in {
            CampaignStatus.completed,
            CampaignStatus.failed,
            CampaignStatus.cancelled,
        }:
            raise CampaignError("Cannot add experiments to a terminal campaign")
        if self.store.count_experiments(campaign_id) >= campaign.max_experiments:
            raise CampaignError("Campaign experiment limit reached")

        experiments = self.store.list_experiments(campaign_id)
        by_id = {experiment.id: experiment for experiment in experiments}
        missing = [parent_id for parent_id in payload.parent_ids if parent_id not in by_id]
        if missing:
            raise CampaignError(f"Unknown parent experiments: {missing}")

        graph = {experiment.id: set(experiment.parent_ids) for experiment in experiments}
        graph["__candidate__"] = set(payload.parent_ids)
        self._assert_acyclic(graph)

        status = (
            ExperimentStatus.queued
            if self._parents_succeeded(payload.parent_ids, by_id)
            else ExperimentStatus.blocked
        )
        experiment = self.store.create_experiment(campaign_id, payload, status)
        self.refresh(campaign_id)
        return experiment

    def refresh(self, campaign_id: str) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        experiments = self.store.list_experiments(campaign_id)
        now = utc_now()

        for experiment in experiments:
            if (
                experiment.status in {ExperimentStatus.leased, ExperimentStatus.running}
                and experiment.lease_expires_at
                and experiment.lease_expires_at <= now
            ):
                next_status = (
                    ExperimentStatus.failed
                    if experiment.attempt >= experiment.max_attempts
                    else ExperimentStatus.queued
                )
                self.store.update_experiment(
                    experiment.id,
                    status=next_status,
                    lease_owner=None,
                    lease_expires_at=None,
                    error="Worker lease expired",
                )

        experiments = self.store.list_experiments(campaign_id)
        by_id = {experiment.id: experiment for experiment in experiments}

        for experiment in experiments:
            if experiment.status != ExperimentStatus.blocked:
                continue
            parent_states = [by_id[parent_id].status for parent_id in experiment.parent_ids]
            if any(
                state in {ExperimentStatus.failed, ExperimentStatus.cancelled}
                for state in parent_states
            ):
                self.store.update_experiment(
                    experiment.id,
                    status=ExperimentStatus.cancelled,
                    error="Dependency did not succeed",
                )
            elif all(state == ExperimentStatus.succeeded for state in parent_states):
                self.store.update_experiment(
                    experiment.id,
                    status=ExperimentStatus.queued,
                    error=None,
                )

        counts = self.store.campaign_status_counts(campaign_id)
        total = sum(counts.values())
        terminal = sum(
            counts.get(state.value, 0)
            for state in self.TERMINAL_EXPERIMENT_STATES
        )
        if campaign.status == CampaignStatus.active and total > 0 and terminal == total:
            failed = counts.get(ExperimentStatus.failed.value, 0)
            final_status = CampaignStatus.failed if failed > 0 else CampaignStatus.completed
            self.store.update_campaign_status(campaign_id, final_status)

        return self.summary(campaign_id)

    def lease_next(
        self,
        campaign_id: str,
        request: ExperimentLeaseRequest,
    ) -> Experiment | None:
        campaign = self._campaign(campaign_id)
        if campaign.status != CampaignStatus.active:
            raise CampaignError("Campaign is not active")
        self.refresh(campaign_id)

        capabilities = set(request.capabilities)
        now = utc_now()
        expires_at = now + timedelta(seconds=request.lease_seconds)

        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active_count = db.execute(
                """
                SELECT COUNT(*) AS n
                FROM experiments
                WHERE campaign_id = ? AND status IN (?, ?)
                """,
                (
                    campaign_id,
                    ExperimentStatus.leased.value,
                    ExperimentStatus.running.value,
                ),
            ).fetchone()["n"]
            if int(active_count) >= campaign.max_parallel:
                return None

            rows = db.execute(
                """
                SELECT * FROM experiments
                WHERE campaign_id = ? AND status = ?
                ORDER BY priority DESC, created_at ASC
                """,
                (campaign_id, ExperimentStatus.queued.value),
            ).fetchall()

            selected = None
            for row in rows:
                required = set(json.loads(row["required_capabilities"]))
                if required.issubset(capabilities):
                    selected = row
                    break
            if selected is None:
                return None

            cursor = db.execute(
                """
                UPDATE experiments
                SET status = ?, attempt = attempt + 1, lease_owner = ?,
                    lease_expires_at = ?, updated_at = ?, error = NULL
                WHERE id = ? AND status = ?
                """,
                (
                    ExperimentStatus.leased.value,
                    request.worker_id,
                    expires_at.isoformat(),
                    now.isoformat(),
                    selected["id"],
                    ExperimentStatus.queued.value,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseConflict("Experiment was leased by another worker")

        return self.store.get_experiment(selected["id"])

    def heartbeat(
        self,
        experiment_id: str,
        payload: ExperimentHeartbeat,
    ) -> Experiment:
        experiment = self._owned_lease(experiment_id, payload.worker_id)
        if experiment.status not in {ExperimentStatus.leased, ExperimentStatus.running}:
            raise LeaseConflict("Experiment is not running")
        return self.store.update_experiment(
            experiment_id,
            status=ExperimentStatus.running,
            lease_expires_at=utc_now() + timedelta(seconds=payload.lease_seconds),
            checkpoint=payload.checkpoint,
        )

    def complete(
        self,
        experiment_id: str,
        payload: ExperimentComplete,
    ) -> Experiment:
        experiment = self._owned_lease(experiment_id, payload.worker_id)
        completed = self.store.update_experiment(
            experiment_id,
            status=ExperimentStatus.succeeded,
            lease_owner=None,
            lease_expires_at=None,
            checkpoint=payload.checkpoint,
            result=payload.result,
            error=None,
        )
        self.refresh(experiment.campaign_id)
        return completed

    def fail(
        self,
        experiment_id: str,
        payload: ExperimentFail,
    ) -> Experiment:
        experiment = self._owned_lease(experiment_id, payload.worker_id)
        retry = payload.retryable and experiment.attempt < experiment.max_attempts
        status = ExperimentStatus.queued if retry else ExperimentStatus.failed
        failed = self.store.update_experiment(
            experiment_id,
            status=status,
            lease_owner=None,
            lease_expires_at=None,
            checkpoint=payload.checkpoint,
            result=payload.result,
            error=payload.error,
        )
        self.refresh(experiment.campaign_id)
        return failed

    def summary(self, campaign_id: str) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        counts = self.store.campaign_status_counts(campaign_id)
        experiments = self.store.list_experiments(campaign_id)
        return {
            "campaign": campaign,
            "counts": counts,
            "experiment_count": len(experiments),
            "ready": counts.get(ExperimentStatus.queued.value, 0),
            "active": (
                counts.get(ExperimentStatus.leased.value, 0)
                + counts.get(ExperimentStatus.running.value, 0)
            ),
            "terminal": sum(
                counts.get(status.value, 0)
                for status in self.TERMINAL_EXPERIMENT_STATES
            ),
        }

    def graph(self, campaign_id: str) -> dict[str, Any]:
        campaign = self._campaign(campaign_id)
        experiments = self.store.list_experiments(campaign_id)
        return {
            "campaign": campaign,
            "nodes": experiments,
            "edges": [
                {"from": parent_id, "to": experiment.id}
                for experiment in experiments
                for parent_id in experiment.parent_ids
            ],
        }

    def _owned_lease(self, experiment_id: str, worker_id: str) -> Experiment:
        experiment = self.store.get_experiment(experiment_id)
        if experiment is None:
            raise KeyError(experiment_id)
        if experiment.lease_owner != worker_id:
            raise LeaseConflict("Worker does not own this experiment lease")
        if experiment.lease_expires_at and experiment.lease_expires_at <= utc_now():
            raise LeaseConflict("Experiment lease has expired")
        return experiment

    def _campaign(self, campaign_id: str) -> Campaign:
        campaign = self.store.get_campaign(campaign_id)
        if campaign is None:
            raise KeyError(campaign_id)
        return campaign

    @staticmethod
    def _parents_succeeded(
        parent_ids: list[str],
        experiments: dict[str, Experiment],
    ) -> bool:
        return all(
            experiments[parent_id].status == ExperimentStatus.succeeded
            for parent_id in parent_ids
        )

    @staticmethod
    def _assert_acyclic(graph: dict[str, set[str]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise CampaignError("Experiment dependency graph contains a cycle")
            if node in visited:
                return
            visiting.add(node)
            for parent in graph.get(node, set()):
                visit(parent)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
