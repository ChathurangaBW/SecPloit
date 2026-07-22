from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, settings
from app.policy import Policy, ValidatedTarget


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Runner:
    def __init__(
        self,
        policy: Policy,
        config: Settings = settings,
    ) -> None:
        self.policy = policy
        self.config = config

    def execute(
        self,
        job_id: str,
        command: str,
        target: ValidatedTarget,
    ) -> CommandResult:
        arguments = self.policy.validate_command(command, target)
        workspace = self._workspace(job_id)

        environment = {
            "PATH": os.environ.get(
                "PATH",
                "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            ),
            "HOME": str(workspace),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }

        started = time.monotonic()
        try:
            completed = subprocess.run(
                arguments,
                cwd=workspace,
                env=environment,
                text=True,
                capture_output=True,
                timeout=self.config.command_timeout_seconds,
                check=False,
            )
            duration = time.monotonic() - started
            return CommandResult(
                command=command,
                exit_code=completed.returncode,
                stdout=self._truncate(completed.stdout),
                stderr=self._truncate(completed.stderr),
                duration_seconds=round(duration, 3),
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            return CommandResult(
                command=command,
                exit_code=124,
                stdout=self._truncate(self._decode(exc.stdout)),
                stderr=self._truncate(self._decode(exc.stderr) or "Command timed out"),
                duration_seconds=round(duration, 3),
                timed_out=True,
            )

    def _workspace(self, job_id: str) -> Path:
        root = self.config.workspace_root.resolve()
        workspace = (root / job_id).resolve()
        if root not in workspace.parents:
            raise ValueError("Invalid workspace path")
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _truncate(self, value: str) -> str:
        limit = self.config.max_output_chars
        if len(value) <= limit:
            return value
        return value[:limit] + "\n...[output truncated]"

    @staticmethod
    def _decode(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value
