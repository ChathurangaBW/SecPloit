from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, settings


class RunnerClient:
    def __init__(
        self,
        config: Settings = settings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self.client = httpx.Client(
            base_url=config.runner_url,
            timeout=httpx.Timeout(30.0, read=config.max_command_seconds + 30),
            headers={"authorization": f"Bearer {config.runner_token}"},
            transport=transport,
        )

    def create_workspace(self, job_id: str) -> dict[str, Any]:
        response = self.client.post("/v1/workspaces", json={"job_id": job_id})
        response.raise_for_status()
        return response.json()

    def execute(
        self,
        workspace_id: str,
        command: str,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> dict[str, Any]:
        response = self.client.post(
            f"/v1/workspaces/{workspace_id}/exec",
            json={
                "command": command,
                "timeout_seconds": timeout_seconds,
                "max_output_bytes": max_output_bytes,
            },
        )
        response.raise_for_status()
        return response.json()

    def list_artifacts(self, workspace_id: str) -> list[dict[str, Any]]:
        response = self.client.get(f"/v1/workspaces/{workspace_id}/artifacts")
        response.raise_for_status()
        return response.json()["artifacts"]

    def delete_workspace(self, workspace_id: str) -> None:
        response = self.client.delete(f"/v1/workspaces/{workspace_id}")
        if response.status_code not in {200, 404}:
            response.raise_for_status()
