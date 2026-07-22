from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import PurePosixPath
from typing import Any

import docker
from docker.errors import NotFound


SAFE_JOB = re.compile(r"^job_[a-f0-9]{32}$")


class DockerWorkspaceBackend:
    def __init__(self) -> None:
        self.client = docker.from_env()
        self.image = os.getenv("SECPLOIT_WORKSPACE_IMAGE", "secploit-runner:latest")
        self.network = os.getenv("SECPLOIT_RANGE_NETWORK", "secploit-range")
        self.memory = os.getenv("SECPLOIT_WORKSPACE_MEMORY", "2g")
        self.cpus = float(os.getenv("SECPLOIT_WORKSPACE_CPUS", "2"))
        self.pids = int(os.getenv("SECPLOIT_WORKSPACE_PIDS", "512"))

    def create(self, job_id: str) -> dict[str, Any]:
        if not SAFE_JOB.fullmatch(job_id):
            raise ValueError("Invalid job id")

        workspace_id = self._workspace_id(job_id)
        name = f"secploit-{workspace_id}"

        try:
            container = self.client.containers.get(name)
            if container.status != "running":
                container.start()
        except NotFound:
            volume_name = f"secploit-{workspace_id}-data"
            self.client.volumes.create(name=volume_name, labels={"secploit.job_id": job_id})
            container = self.client.containers.run(
                image=self.image,
                name=name,
                command=["sleep", "infinity"],
                detach=True,
                user="1000:1000",
                working_dir="/workspace",
                network=self.network,
                environment={"HOME": "/workspace", "SECPLOIT_JOB_ID": job_id},
                volumes={volume_name: {"bind": "/workspace", "mode": "rw"}},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                read_only=True,
                tmpfs={
                    "/tmp": "rw,noexec,nosuid,size=256m",
                    "/run": "rw,noexec,nosuid,size=32m",
                },
                mem_limit=self.memory,
                nano_cpus=int(self.cpus * 1_000_000_000),
                pids_limit=self.pids,
                labels={
                    "secploit.managed": "true",
                    "secploit.job_id": job_id,
                    "secploit.workspace_id": workspace_id,
                },
            )

        container.reload()
        return {
            "workspace_id": workspace_id,
            "container_id": container.id,
            "status": container.status,
            "network": self.network,
            "image": self.image,
            "tools": self.tools(),
        }

    def execute(
        self,
        workspace_id: str,
        command: str,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> dict[str, Any]:
        container = self._container(workspace_id)
        wrapped = [
            "timeout",
            "--signal=TERM",
            "--kill-after=5",
            str(timeout_seconds),
            "/bin/bash",
            "-lc",
            command,
        ]
        started = time.monotonic()
        result = container.exec_run(
            cmd=wrapped,
            user="1000:1000",
            workdir="/workspace",
            demux=True,
            environment={"HOME": "/workspace"},
        )
        duration = time.monotonic() - started

        stdout_raw, stderr_raw = result.output or (b"", b"")
        stdout = self._decode(stdout_raw, max_output_bytes)
        stderr = self._decode(stderr_raw, max_output_bytes)
        exit_code = int(result.exit_code)

        return {
            "command": command,
            "exit_code": exit_code,
            "timed_out": exit_code in {124, 137},
            "duration_seconds": round(duration, 3),
            "stdout": stdout,
            "stderr": stderr,
            "output_truncated": (
                len(stdout_raw or b"") > max_output_bytes
                or len(stderr_raw or b"") > max_output_bytes
            ),
        }

    def artifacts(self, workspace_id: str) -> list[dict[str, Any]]:
        container = self._container(workspace_id)
        result = container.exec_run(
            cmd=[
                "/bin/bash",
                "-lc",
                r"""find /workspace -type f -printf '%P\t%s\t%T@
' 2>/dev/null | sort""",
            ],
            user="1000:1000",
            workdir="/workspace",
        )
        if result.exit_code != 0:
            return []

        artifacts: list[dict[str, Any]] = []
        for line in result.output.decode("utf-8", "replace").splitlines():
            try:
                path, size, modified = line.split("\t", 2)
                normalized = str(PurePosixPath(path))
                if normalized.startswith("../"):
                    continue
                artifacts.append(
                    {"path": normalized, "size": int(size), "modified": float(modified)}
                )
            except (ValueError, TypeError):
                continue
        return artifacts[:2000]

    def delete(self, workspace_id: str) -> None:
        try:
            container = self._container(workspace_id)
        except NotFound:
            return

        mounts = container.attrs.get("Mounts", [])
        volume_names = [
            mount["Name"]
            for mount in mounts
            if mount.get("Type") == "volume" and mount.get("Name")
        ]
        container.remove(force=True)
        for name in volume_names:
            try:
                self.client.volumes.get(name).remove(force=True)
            except NotFound:
                pass

    def health(self) -> dict[str, Any]:
        self.client.ping()
        try:
            self.client.networks.get(self.network)
            network_ready = True
        except NotFound:
            network_ready = False
        return {
            "status": "ok",
            "docker": True,
            "network": self.network,
            "network_ready": network_ready,
            "image": self.image,
        }

    def _container(self, workspace_id: str):
        if not re.fullmatch(r"ws_[a-f0-9]{20}", workspace_id):
            raise ValueError("Invalid workspace id")
        return self.client.containers.get(f"secploit-{workspace_id}")

    @staticmethod
    def _workspace_id(job_id: str) -> str:
        digest = hashlib.sha256(job_id.encode()).hexdigest()[:20]
        return f"ws_{digest}"

    @staticmethod
    def _decode(value: bytes | None, limit: int) -> str:
        raw = value or b""
        if len(raw) > limit:
            raw = raw[:limit] + b"\n[output truncated by SecPloit]\n"
        return raw.decode("utf-8", "replace")

    @staticmethod
    def tools() -> list[str]:
        return [
            "bash",
            "python3",
            "gcc",
            "gdb",
            "radare2",
            "binwalk",
            "checksec",
            "strace",
            "nmap",
            "nikto",
            "ffuf",
            "gobuster",
            "sqlmap",
            "semgrep",
            "secploit-browser",
            "chromium",
            "curl",
            "openssl",
            "dig",
            "nslookup",
            "whois",
            "netcat",
            "git",
            "jq",
        ]
