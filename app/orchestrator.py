from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.config import Settings, settings
from app.llm import LLM, OpenAIResponsesLLM
from app.models import (
    JobStatus,
    OperatorDecision,
    ReportAudit,
    ResearchPlan,
    SpecialistAssessment,
    StepReview,
)
from app.policy import Policy, PolicyError
from app.runner_client import RunnerClient
from app.store import Store


SCOUT_BASE_INSTRUCTIONS = """
You are one specialist in SecPloit's planning committee. The engagement is confined to an isolated,
explicitly authorized cyber range. Analyze the objective from your assigned specialty and return a
small set of high-value, evidence-producing hypotheses and actions for the lead planner.

The operator has a persistent Kali workspace with a general shell, browser automation, web and
network tooling, source-analysis tooling, compilers, debuggers, and binary-analysis utilities. The
workspace cannot reach the public internet.

Do not propose persistence, denial of service, destructive actions, host escape, credential reuse
outside the range, or interaction with any system other than the supplied target.
""".strip()

SCOUT_PROFILES: tuple[tuple[str, str], ...] = (
    (
        "web_application",
        "Focus on routes, browser-visible behavior, authentication/session boundaries, APIs, input "
        "handling, client-side code, and reproducible HTTP evidence.",
    ),
    (
        "network_protocol",
        "Focus on exposed services, protocol behavior, TLS, service versions, trust boundaries, and "
        "safe protocol-level validation.",
    ),
    (
        "code_and_binary",
        "Focus on available source, packages, scripts, binaries, data-flow, unsafe sinks, build "
        "artifacts, debugging, and test-harness opportunities.",
    ),
    (
        "skeptical_reviewer",
        "Challenge likely assumptions, identify false-positive risks, define minimum evidence for "
        "each claim, and suggest discriminating tests.",
    ),
    (
        "authentication",
        "Focus on identity, authorization, session state, role boundaries, token handling, and "
        "evidence needed to distinguish authentication from authorization defects.",
    ),
    (
        "research_strategy",
        "Focus on sequencing, information gain, failure recovery, artifact creation, and efficient "
        "use of the command and wall-clock budget.",
    ),
)

PLANNER_INSTRUCTIONS = """
You are the lead planning component of SecPloit, an autonomous security research system operating
only inside an isolated, explicitly authorized cyber range.

Synthesize the specialist assessments into one concrete research plan. Resolve conflicts, prefer
hypotheses with discriminating tests, and define completion criteria that require reproducible
evidence rather than scanner labels. Prefer high-information actions over generic checklists.

The operator has a persistent Kali workspace with a general shell and common browser, web, network,
source-analysis, binary-analysis, compilation, and debugging tools. The workspace cannot reach the
public internet.

Do not propose persistence, denial of service, destructive actions, host escape, credential reuse
outside the range, or attacks against anything beyond the supplied target.
""".strip()

OPERATOR_INSTRUCTIONS = """
You are the hands-on operator of SecPloit inside an isolated authorized cyber range.

Choose exactly one next action. You may write scripts, create files, compile programs, use pipelines,
inspect source, operate the bounded browser helper, enumerate services, fuzz carefully, and validate
vulnerabilities against the supplied range target. The workspace persists across steps.

Rules:
- One shell command per decision. Compound shell programs and heredocs are allowed.
- Base claims on observed evidence.
- Use the planning committee as hypotheses, not as facts.
- Prefer tests that distinguish competing explanations.
- Do not repeat failed commands without a meaningful change.
- Do not attempt host escape, Docker access, persistence, destructive actions, denial of service,
  or interaction with systems outside the supplied target.
- Select action=finish only when the objective is answered or the remaining paths have low value.
""".strip()

REVIEWER_INSTRUCTIONS = """
You are the critical evidence reviewer for an autonomous security assessment in an isolated cyber
range.

Evaluate the operator command and its output. Separate confirmed evidence from speculation. A finding
needs a concrete affected component and reproducible evidence. Reduce confidence when output is
ambiguous, tool-generated only, or not independently validated. Detect duplicates and contradictions.
Do not reward activity; reward correct conclusions and useful next hypotheses.
""".strip()

REPORT_AUDITOR_INSTRUCTIONS = """
You are the final evidence auditor for a private cyber-range assessment. Review all candidate findings,
command evidence, specialist assumptions, and artifacts. Mark which finding titles are adequately
supported and which must be rejected or downgraded. Identify material caveats. Do not create new
vulnerability claims.
""".strip()

REPORTER_INSTRUCTIONS = """
Write a professional penetration-test report from the supplied SecPloit transcript and final evidence
audit.

Use these sections:
1. Executive summary
2. Scope and methodology
3. Confirmed findings, ordered by severity
4. Rejected or unconfirmed hypotheses
5. Non-vulnerability observations
6. Remediation priorities
7. Commands, artifacts, and evidence limitations

Never upgrade hypotheses into confirmed findings. Respect the final evidence audit, include concise
reproduction evidence, and identify material limitations. The engagement occurred in an isolated
authorized cyber range.
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

            committee = self._run_planning_committee(
                job_id=job_id,
                target=target.original,
                objective=job.objective,
                tools=workspace.get("tools", []),
                step_budget=job.max_steps,
            )

            plan = self.llm.structured(
                model=self.config.openai_model,
                role="plan",
                instructions=PLANNER_INSTRUCTIONS,
                payload={
                    "target": target.original,
                    "objective": job.objective,
                    "step_budget": job.max_steps,
                    "available_tools": workspace.get("tools", []),
                    "specialist_assessments": [
                        assessment.model_dump(mode="json") for assessment in committee
                    ],
                },
                schema=ResearchPlan,
                effort=self.config.openai_reasoning_effort,
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
            seen_finding_keys: set[str] = set()
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
                existing_findings = [
                    finding.model_dump(mode="json")
                    for finding in self.store.get_findings(job_id)
                ]
                decision = self.llm.structured(
                    model=self.config.openai_model,
                    role="operator",
                    instructions=OPERATOR_INSTRUCTIONS,
                    payload={
                        "target": target.original,
                        "objective": job.objective,
                        "plan": plan.model_dump(mode="json"),
                        "specialist_assessments": [
                            assessment.model_dump(mode="json") for assessment in committee
                        ],
                        "confirmed_findings": existing_findings,
                        "step": step,
                        "remaining_steps": job.max_steps - step + 1,
                        "transcript": transcript[-16:],
                    },
                    schema=OperatorDecision,
                    effort=self.config.openai_operator_reasoning_effort,
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
                        "prior_findings": existing_findings,
                    },
                    schema=StepReview,
                    effort=self.config.openai_critic_reasoning_effort,
                )
                self.store.add_event(
                    job_id,
                    step,
                    "review",
                    review.summary,
                    review.model_dump(mode="json"),
                )

                for finding in review.findings:
                    finding_key = "|".join(
                        [
                            finding.title.strip().lower(),
                            finding.claim.strip().lower(),
                        ]
                    )
                    if finding_key in seen_finding_keys:
                        self.store.add_event(
                            job_id,
                            step,
                            "finding_duplicate",
                            finding.title,
                            {"claim": finding.claim},
                        )
                        continue
                    seen_finding_keys.add(finding_key)
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

            audit = self.llm.structured(
                model=self.config.critic_model,
                role="report_audit",
                instructions=REPORT_AUDITOR_INSTRUCTIONS,
                payload={
                    "target": target.original,
                    "objective": job.objective,
                    "plan": plan.model_dump(mode="json"),
                    "specialist_assessments": [
                        assessment.model_dump(mode="json") for assessment in committee
                    ],
                    "candidate_findings": findings,
                    "transcript": transcript,
                    "artifacts": artifacts,
                },
                schema=ReportAudit,
                effort=self.config.openai_critic_reasoning_effort,
            )
            self.store.add_event(
                job_id,
                job.max_steps,
                "report_audit",
                audit.summary,
                audit.model_dump(mode="json"),
            )

            report = self.llm.text(
                model=self.config.critic_model,
                role="report",
                instructions=REPORTER_INSTRUCTIONS,
                payload={
                    "target": target.original,
                    "objective": job.objective,
                    "plan": plan.model_dump(mode="json"),
                    "specialist_assessments": [
                        assessment.model_dump(mode="json") for assessment in committee
                    ],
                    "findings": findings,
                    "final_evidence_audit": audit.model_dump(mode="json"),
                    "transcript": transcript,
                    "artifacts": artifacts,
                },
                effort=self.config.openai_critic_reasoning_effort,
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

    def _run_planning_committee(
        self,
        *,
        job_id: str,
        target: str,
        objective: str,
        tools: list[str],
        step_budget: int,
    ) -> list[SpecialistAssessment]:
        profiles = SCOUT_PROFILES[: self.config.planning_agents]
        assessments: dict[str, SpecialistAssessment] = {}

        def run_specialist(role: str, specialty: str) -> SpecialistAssessment:
            return self.llm.structured(
                model=self.config.openai_model,
                role=f"scout_{role}",
                instructions=f"{SCOUT_BASE_INSTRUCTIONS}\n\nSpecialty:\n{specialty}",
                payload={
                    "assigned_role": role,
                    "target": target,
                    "objective": objective,
                    "step_budget": step_budget,
                    "available_tools": tools,
                },
                schema=SpecialistAssessment,
                effort=self.config.openai_reasoning_effort,
            )

        with ThreadPoolExecutor(max_workers=len(profiles)) as executor:
            future_roles = {
                executor.submit(run_specialist, role, specialty): role
                for role, specialty in profiles
            }
            for future in as_completed(future_roles):
                role = future_roles[future]
                try:
                    assessment = future.result()
                    assessments[role] = assessment
                    self.store.add_event(
                        job_id,
                        0,
                        "specialist_assessment",
                        f"{role}: {assessment.summary}",
                        assessment.model_dump(mode="json"),
                    )
                except Exception as exc:
                    self.store.add_event(
                        job_id,
                        0,
                        "specialist_error",
                        f"{role} specialist failed",
                        {"error": f"{type(exc).__name__}: {exc}"},
                    )

        return [assessments[role] for role, _ in profiles if role in assessments]

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
