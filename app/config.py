from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
ReasoningMode = Literal["standard", "pro"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "SecPloit"
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.6", alias="OPENAI_MODEL")
    openai_critic_model: str = Field(default="", alias="OPENAI_CRITIC_MODEL")
    openai_reasoning_effort: ReasoningEffort = Field(
        default="high",
        alias="OPENAI_REASONING_EFFORT",
    )
    openai_operator_reasoning_effort: ReasoningEffort = Field(
        default="high",
        alias="OPENAI_OPERATOR_REASONING_EFFORT",
    )
    openai_critic_reasoning_effort: ReasoningEffort = Field(
        default="high",
        alias="OPENAI_CRITIC_REASONING_EFFORT",
    )
    openai_reasoning_mode: ReasoningMode = Field(
        default="standard",
        alias="OPENAI_REASONING_MODE",
    )
    openai_max_output_tokens: int = Field(
        default=24000,
        alias="OPENAI_MAX_OUTPUT_TOKENS",
        ge=1024,
        le=128000,
    )
    openai_store_responses: bool = Field(
        default=False,
        alias="OPENAI_STORE_RESPONSES",
    )
    planning_agents: int = Field(
        default=4,
        alias="SECPLOIT_PLANNING_AGENTS",
        ge=1,
        le=8,
    )
    database_path: str = Field(default="/data/secploit.sqlite3", alias="SECPLOIT_DATABASE_PATH")
    runner_url: str = Field(default="http://runner:9000", alias="SECPLOIT_RUNNER_URL")
    runner_token: str = Field(
        default="change-this-runner-token",
        alias="SECPLOIT_RUNNER_TOKEN",
    )
    target_allowlist: str = Field(
        default="juice-shop,dvwa,localhost,127.0.0.1",
        alias="SECPLOIT_TARGET_ALLOWLIST",
    )
    max_steps: int = Field(default=30, alias="SECPLOIT_MAX_STEPS", ge=1, le=200)
    max_wall_seconds: int = Field(
        default=1800,
        alias="SECPLOIT_MAX_WALL_SECONDS",
        ge=60,
        le=21600,
    )
    max_command_seconds: int = Field(
        default=180,
        alias="SECPLOIT_MAX_COMMAND_SECONDS",
        ge=5,
        le=1800,
    )
    max_output_bytes: int = Field(
        default=120000,
        alias="SECPLOIT_MAX_OUTPUT_BYTES",
        ge=4096,
        le=2_000_000,
    )

    @field_validator("runner_url")
    @classmethod
    def normalize_runner_url(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def allowed_targets(self) -> tuple[str, ...]:
        return tuple(
            item.strip().lower().rstrip(".")
            for item in self.target_allowlist.split(",")
            if item.strip()
        )

    @property
    def critic_model(self) -> str:
        return self.openai_critic_model or self.openai_model

    def reasoning_effort_for(self, role: str) -> ReasoningEffort:
        if role == "operator":
            return self.openai_operator_reasoning_effort
        if role in {"review", "report", "report_audit"}:
            return self.openai_critic_reasoning_effort
        return self.openai_reasoning_effort

    def reasoning_options_for(
        self,
        role: str,
        effort: ReasoningEffort | None = None,
    ) -> dict[str, str]:
        options = {"effort": effort or self.reasoning_effort_for(role)}
        if self.openai_reasoning_mode == "pro":
            options["mode"] = "pro"
        return options


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
