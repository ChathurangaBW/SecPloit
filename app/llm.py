from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from openai import OpenAI
from pydantic import BaseModel

from app.config import ReasoningEffort, Settings, settings


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLM(Protocol):
    def structured(
        self,
        *,
        model: str,
        role: str,
        instructions: str,
        payload: dict[str, Any],
        schema: type[SchemaT],
        effort: ReasoningEffort | None = None,
    ) -> SchemaT: ...

    def text(
        self,
        *,
        model: str,
        role: str,
        instructions: str,
        payload: dict[str, Any],
        effort: ReasoningEffort | None = None,
    ) -> str: ...


class OpenAIResponsesLLM:
    def __init__(
        self,
        config: Settings = settings,
        client: "OpenAI | None" = None,
    ) -> None:
        self.config = config
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=config.openai_api_key)
        self.client = client

    def structured(
        self,
        *,
        model: str,
        role: str,
        instructions: str,
        payload: dict[str, Any],
        schema: type[SchemaT],
        effort: ReasoningEffort | None = None,
    ) -> SchemaT:
        schema_name = f"secploit_{role}"[:64]
        selected_effort = effort or self.config.reasoning_effort_for(role)
        previous_raw = ""

        for attempt in range(2):
            attempt_instructions = instructions
            attempt_payload: dict[str, Any] = payload
            if attempt:
                attempt_instructions = (
                    instructions
                    + "\nThe previous answer did not validate. Return only one JSON object "
                    "that exactly matches the supplied schema. Do not use Markdown fences."
                )
                attempt_payload = {
                    "request": payload,
                    "invalid_previous_output": previous_raw[:12000],
                    "required_schema": schema.model_json_schema(),
                }

            request: dict[str, Any] = {
                "model": model,
                "instructions": attempt_instructions,
                "input": json.dumps(attempt_payload, ensure_ascii=False),
                "reasoning": {"effort": selected_effort},
                "max_output_tokens": self.config.openai_max_output_tokens,
                "store": self.config.openai_store_responses,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": schema.model_json_schema(),
                        "strict": True,
                    }
                },
            }

            response = self._create_response(
                request=request,
                fallback_instructions=(
                    attempt_instructions
                    + "\nReturn only JSON matching this schema:\n"
                    + json.dumps(schema.model_json_schema(), ensure_ascii=False)
                ),
                fallback_input=json.dumps(attempt_payload, ensure_ascii=False),
            )
            previous_raw = response.output_text.strip()
            try:
                return schema.model_validate_json(previous_raw)
            except Exception:
                if attempt == 1:
                    raise RuntimeError(
                        f"{role} returned invalid structured output: {previous_raw[:1000]}"
                    )

        raise RuntimeError(f"{role} did not return structured output")

    def text(
        self,
        *,
        model: str,
        role: str,
        instructions: str,
        payload: dict[str, Any],
        effort: ReasoningEffort | None = None,
    ) -> str:
        selected_effort = effort or self.config.reasoning_effort_for(role)
        request: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": json.dumps(payload, ensure_ascii=False),
            "reasoning": {"effort": selected_effort},
            "max_output_tokens": self.config.openai_max_output_tokens,
            "store": self.config.openai_store_responses,
        }
        response = self._create_response(
            request=request,
            fallback_instructions=instructions,
            fallback_input=json.dumps(payload, ensure_ascii=False),
        )
        return response.output_text.strip()

    def _create_response(
        self,
        *,
        request: dict[str, Any],
        fallback_instructions: str,
        fallback_input: str,
    ):
        try:
            return self.client.responses.create(**request)
        except TypeError:
            return self.client.responses.create(
                model=request["model"],
                instructions=fallback_instructions,
                input=fallback_input,
            )
