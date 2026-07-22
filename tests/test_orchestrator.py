from __future__ import annotations

from typing import Any

from app.config import Settings
from app.models import OperatorDecision, ResearchPlan, StepReview
from app.orchestrator import Orchestrator
from app.policy import Policy
from app.store import Store


class FakeLLM:
    def __init__(self) -> None:
        self.operator_calls = 0

    def structured(
        self,
        *,
        model: str,
        role: str,
        instructions: str,
        payload: dict[str, Any],
        schema,
    ):
        if schema is ResearchPlan:
            return ResearchPlan(
                summary="Inspect the service and validate one observation.",
                hypotheses=[],
                initial_commands=["curl -I http://dvwa"],
                completion_criteria=["One evidence-backed observation"],
            )
        if schema is OperatorDecision:
            self.operator_calls += 1
            if self.operator_calls == 1:
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
        raise AssertionError(schema)

    def text(
        self,
        *,
        model: str,
        instructions: str,
        payload: dict[str, Any],
    ) -> str:
        return "Final evidence-based report."


class FakeRunner:
    def create_workspace(self, job_id: str) -> dict[str, Any]:
        return {
            "workspace_id": "ws_0123456789abcdefabcd",
            "tools": ["curl"],
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


def test_orchestrator_completes(tmp_path) -> None:
    config = Settings(
        OPENAI_API_KEY="test",
        OPENAI_MODEL="test-model",
        SECPLOIT_DATABASE_PATH=str(tmp_path / "test.sqlite3"),
        SECPLOIT_TARGET_ALLOWLIST="dvwa",
        SECPLOIT_MAX_STEPS=5,
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
    assert any(event.kind == "command_result" for event in store.get_events(job.id))
