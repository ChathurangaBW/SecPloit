from __future__ import annotations

import time
from typing import Any

from app.config import Settings, settings
from app.llm import LLM, OpenAIResponsesLLM
from app.models import JobStatus, OperatorDecision, ResearchPlan, StepReview
from app.policy import Policy, PolicyError
from app.runner_client import RunnerClient
from app.store import Store


PLANNER_INSTRUCTIONS = """
You are the planning component of SecPloit, an autonomous security research system operating only
inside an isolated, explicitly authorized cyber range.

Produce a concrete research plan. Prefer evidence-producing actions over generic checklists.
The operator has a persistent Kali workspace with a general shell and common web, network,
source-analysis, binary-analysis, and debugging tools. The workspace cannot reach the public internet.

Do not propose persistence, denial of service, destructive actions, host escape, credential reuse
outside the range, or attacks against anything beyond the supplied target.
""".strip()

OPERATOR_INSTRUCTIONS = """
You are the hands-on operator of SecPloit inside an isolated authorized cyber range.

Choose exactly one next action. You may write scripts, create files, compile programs, use pipelines,
inspect source, enumerate services, fuzz carefully, and validate vulnerabilities against the supplied
range target. The workspace persists across steps.

Rules:
- One shell command per decision. Compound shell programs and heredocs are allowed.
- Base claims on observed evidence.
- Do not repeat failed commands without a meaningful change.
- Do not attempt host escape, Docker access, persistence, destructive actions, denial of service,
  or interaction with systems outside the supplied target.
- Select action=finish only when the objective is answered or the remaining paths have low value.
""".strip()

REVIEWER_INSTRUCTIONS = """
You are the critical reviewer for an autonomous security assessment in an isolated cyber range.

Evaluate the operator command and its output. Separate confirmed evidence from speculation.
A finding needs a concrete affected component and reproducible evidence. Reduce confidence when
output is ambiguous, tool-generated only, or not independently validated. Do not reward activity;
reward correct conclusions and useful next hypotheses.
""".strip()

REPORTER_INSTRUCTIONS = """
Write a professional penetration-test report from the supplied SecPloit transcript.

Use these sections:
1. Executive summary
2. Scope and methodology
3. Confirmed findings, ordered by severity
4. Non-vulnerability observations
5. Remediation priorities
6. Commands and evidence limitations

Never upgrade hypotheses into confirmed findings. Include concise reproduction evidence and identify
material limitations. The engagement occurred in an isolated authorized cyber range.
""".strip()


class Orchestrator:
    def __init__(
        self,
        store: Store,
        config: Settings = settings,
        llm: LLM | None = None,
        runner: RunnerClient | None = None,
        policy: Policy | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.llm = llm or OpenAIResponsesLLM(config)
        self.runner = runner or RunnerClient(config)
        self.policy = policy or Policy(config)

    def run(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)

        workspace_id: str | None = None
        started = time.monotonic()

        try:
            target = self.policy.validate_target(job.target)
            self.store.update_job(job_id, status=JobStatus.planning, error=None)
            self.store.add_event(
                job_id,
                0,
                "status",
                "Creating isolated workspace",
                {"target": target.original, "host": target.host},
            )

            workspace = self.runner.create_workspace(job_id)
            workspace_id = workspace["workspace_id"]
            self.store.update_job(job_id, workspace_id=workspace_id)
            self.store.add_event(job_id, 0, "workspace", "Workspace ready", workspace)

            plan = self.llm.structured(
                model=self.config.openai_model,
                role="plan",
                instructions=PLANNER_INSTRUCTIONS,
                payload={
                    "target": target.original,
                    "objective": job.objective,
                    "step_budget": job.max_steps,
                    "available_tools": workspace.get("tools", []),
                },
                schema=ResearchPlan,
            )
            self.store.add_event(
                job_id,
                0,
                "plan",
                plan.summary,
                plan.model_dump(mode="json"),
            )
            self.store.update_job(job_id, status=JobStatus.running)

            transcript: list[dict[str, Any]] = []
            for step in range(1, job.max_steps + 1):
                current = self.store.get_job(job_id)
                if current is None:
                    raise KeyError(job_id)
                if current.cancel_requested:
                    self.store.update_job(job_id, status=JobStatus.cancelled)
                    self.store.add_event(job_id, step, "status", "Engagement cancelled")
                    return
                if time.monotonic() - started > self.config.max_wall_seconds:
                    self.store.add_event(job_id, step, "budget", "Wall-clock budget exhausted")
                    break

                self.store.update_job(job_id, current_step=step)
                decision = self.llm.structured(
                    model=self.config.openai_model,
                    role="operator",
                    instructions=OPERATOR_INSTRUCTIONS,
                    payload={
                        "target": target.original,
                        "objective": job.objective,
                        "plan": plan.model_dump(mode="json"),
                        "step": step,
                        "remaining_steps": job.max_steps - step + 1,
                        "transcript": transcript[-12:],
                    },
                    schema=OperatorDecision,
                )
                self.store.add_event(
                    job_id,
                    step,
                    "decision",
                    decision.rationale,
                    {
                        "action": decision.action,
                        "command": decision.command,
                        "expected_signal": decision.expected_signal,
                    },
                )

                if decision.action == "finish":
                    if decision.report:
                        transcript.append(
                            {
                                "step": step,
                                "type": "operator_finish",
                                "content": decision.report,
                            }
                        )
                    break

                command = self.policy.validate_command(decision.command)
                result = self.runner.execute(
                    workspace_id=workspace_id,
                    command=command,
                    timeout_seconds=self.config.max_command_seconds,
                    max_output_bytes=self.config.max_output_bytes,
                )
                self.store.add_event(
                    job_id,
                    step,
                    "command_result",
                    f"Command exited with code {result['exit_code']}",
                    result,
                )

                review = self.llm.structured(
                    model=self.config.critic_model,
                    role="review",
                    instructions=REVIEWER_INSTRUCTIONS,
                    payload={
                        "target": target.original,
                        "objective": job.objective,
                        "step": step,
                        "operator_rationale": decision.rationale,
                        "expected_signal": decision.expected_signal,
                        "command": command,
                        "result": result,
                    },
                    schema=StepReview,
                )
                self.store.add_event(
                    job_id,
                    step,
                    "review",
                    review.summary,
                    review.model_dump(mode="json"),
                )

                for finding in review.findings:
                    saved = self.store.add_finding(
                        job_id=job_id,
                        title=finding.title,
                        severity=finding.severity,
                        confidence=finding.confidence,
                        claim=finding.claim,
                        evidence=finding.evidence,
                        remediation=finding.remediation or None,
                    )
                    self.store.add_event(
                        job_id,
                        step,
                        "finding",
                        finding.title,
                        saved.model_dump(mode="json"),
                    )

                transcript.append(
                    {
                        "step": step,
                        "command": command,
                        "rationale": decision.rationale,
                        "result": {
                            "exit_code": result["exit_code"],
                            "timed_out": result["timed_out"],
                            "stdout": result["stdout"][-30000:],
                            "stderr": result["stderr"][-12000:],
                        },
                        "review": review.model_dump(mode="json"),
                    }
                )
                if review.should_stop:
                    break

            self.store.update_job(job_id, status=JobStatus.reporting)
            findings = [
                finding.model_dump(mode="json")
                for finding in self.store.get_findings(job_id)
            ]
            artifacts = self.runner.list_artifacts(workspace_id)

            report = self.llm.text(
                model=self.config.critic_model,
                instructions=REPORTER_INSTRUCTIONS,
                payload={
                    "target": target.original,
                    "objective": job.objective,
                    "plan": plan.model_dump(mode="json"),
                    "findings": findings,
                    "transcript": transcript,
                    "artifacts": artifacts,
                },
            )
            self.store.update_job(job_id, status=JobStatus.completed, report=report)
            self.store.add_event(
                job_id,
                job.max_steps,
                "report",
                "Final report generated",
                {"report": report, "artifacts": artifacts},
            )

        except PolicyError as exc:
            self._fail(job_id, f"PolicyError: {exc}")
        except Exception as exc:
            self._fail(job_id, f"{type(exc).__name__}: {exc}")

    def cancel(self, job_id: str) -> None:
        job = self.store.request_cancel(job_id)
        if job.workspace_id:
            try:
                self.runner.delete_workspace(job.workspace_id)
            except Exception:
                pass

    def _fail(self, job_id: str, error: str) -> None:
        self.store.update_job(job_id, status=JobStatus.failed, error=error)
        self.store.add_event(job_id, 0, "error", "Engagement failed", {"error": error})
