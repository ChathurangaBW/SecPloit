from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "SecPloit"
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.2", alias="OPENAI_MODEL")
    openai_critic_model: str = Field(default="", alias="OPENAI_CRITIC_MODEL")
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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
