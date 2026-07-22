from __future__ import annotations

from threading import Lock
from typing import Any

from app.config import Settings
from app.models import (
    OperatorDecision,
    ReportAudit,
    ResearchPlan,
    SpecialistAssessment,
    StepReview,
)
from app.orchestrator import Orchestrator
from app.policy import Policy
from app.store import Store


class FakeLLM:
    def __init__(self) -> None:
        self.operator_calls = 0
        self._lock = Lock()

    def structured(
        self,
        *,
        model: str,
        role: str,
        instructions: str,
        payload: dict[str, Any],
        schema,
        effort=None,
    ):
        if schema is SpecialistAssessment:
            assigned_role = payload["assigned_role"]
            return SpecialistAssessment(
                role=assigned_role,
                summary=f"Assessment from {assigned_role}",
                hypotheses=[],
                recommended_actions=["curl -I http://dvwa"],
                evidence_requirements=["Direct HTTP response"],
                caveats=[],
            )
        if schema is ResearchPlan:
            assert len(payload["specialist_assessments"]) == 2
            return ResearchPlan(
                summary="Inspect the service and validate one observation.",
                hypotheses=[],
                initial_commands=["curl -I http://dvwa"],
                completion_criteria=["One evidence-backed observation"],
            )
        if schema is OperatorDecision:
            with self._lock:
                self.operator_calls += 1
                call_number = self.operator_calls
            if call_number == 1:
                return OperatorDecision(
                    action="run",
                    command="curl -I http://dvwa",
                    rationale="Collect HTTP headers",
                    expected_signal="Response headers",
                )
            return OperatorDecision(
                action="finish",
                rationale="Objective complete",
                report="done",
            )
        if schema is StepReview:
            return StepReview(
                summary="Observed an HTTP response.",
                findings=[],
                next_focus="Finish",
                should_stop=True,
            )
        if schema is ReportAudit:
            return ReportAudit(
                summary="No vulnerability finding required final acceptance.",
                accepted_finding_titles=[],
                rejected_finding_titles=[],
                material_caveats=[],
            )
        raise AssertionError(schema)

    def text(
        self,
        *,
        model: str,
        role: str,
        instructions: str,
        payload: dict[str, Any],
        effort=None,
    ) -> str:
        assert role == "report"
        assert "final_evidence_audit" in payload
        return "Final evidence-based report."


class FakeRunner:
    def create_workspace(self, job_id: str) -> dict[str, Any]:
        return {
            "workspace_id": "ws_0123456789abcdefabcd",
            "tools": ["curl", "secploit-browser"],
            "network": "test",
        }

    def execute(
        self,
        workspace_id: str,
        command: str,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> dict[str, Any]:
        return {
            "command": command,
            "exit_code": 0,
            "timed_out": False,
            "duration_seconds": 0.1,
            "stdout": "HTTP/1.1 200 OK",
            "stderr": "",
            "output_truncated": False,
        }

    def list_artifacts(self, workspace_id: str) -> list[dict[str, Any]]:
        return []

    def delete_workspace(self, workspace_id: str) -> None:
        return None


def test_orchestrator_completes_with_committee_and_audit(tmp_path) -> None:
    config = Settings(
        OPENAI_API_KEY="test",
        OPENAI_MODEL="test-model",
        SECPLOIT_DATABASE_PATH=str(tmp_path / "test.sqlite3"),
        SECPLOIT_TARGET_ALLOWLIST="dvwa",
        SECPLOIT_MAX_STEPS=5,
        SECPLOIT_PLANNING_AGENTS=2,
    )
    store = Store(config.database_path)
    store.initialize()
    job = store.create_job("http://dvwa", "Assess the authorized test service", 3)

    orchestrator = Orchestrator(
        store=store,
        config=config,
        llm=FakeLLM(),
        runner=FakeRunner(),
        policy=Policy(config),
    )
    orchestrator.run(job.id)

    loaded = store.get_job(job.id)
    assert loaded is not None
    assert loaded.status.value == "completed"
    assert loaded.report == "Final evidence-based report."
    events = store.get_events(job.id)
    assert any(event.kind == "command_result" for event in events)
    assert len([event for event in events if event.kind == "specialist_assessment"]) == 2
    assert any(event.kind == "report_audit" for event in events)
