from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Autonomous Security Research Agent"
    openai_model: str = "gpt-5"

    database_path: Path = Path("data/agent.db")
    workspace_root: Path = Path("data/workspaces")

    target_allowlist: str = "localhost,127.0.0.1"
    command_allowlist: str = (
        "curl,nmap,dig,nslookup,whois,openssl,jq,grep,sed,awk,cat,head,tail,"
        "ls,find,pwd,mkdir,cp,mv,touch,printf,echo"
    )

    command_timeout_seconds: int = 120
    max_output_chars: int = 20_000
    default_max_steps: int = 12
    max_max_steps: int = 40

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_targets(self) -> tuple[str, ...]:
        return tuple(
            value.strip().lower().rstrip(".")
            for value in self.target_allowlist.split(",")
            if value.strip()
        )

    @property
    def allowed_commands(self) -> frozenset[str]:
        return frozenset(
            value.strip()
            for value in self.command_allowlist.split(",")
            if value.strip()
        )


settings = Settings()
