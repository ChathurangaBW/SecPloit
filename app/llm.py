from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from openai import OpenAI
from pydantic import BaseModel

from app.config import Settings, settings


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
    ) -> SchemaT: ...

    def text(
        self,
        *,
        model: str,
        instructions: str,
        payload: dict[str, Any],
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
    ) -> SchemaT:
        schema_name = f"secploit_{role}"
        request = {
            "model": model,
            "instructions": instructions,
            "input": json.dumps(payload, ensure_ascii=False),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema.model_json_schema(),
                    "strict": True,
                }
            },
        }

        try:
            response = self.client.responses.create(**request)
        except TypeError:
            response = self.client.responses.create(
                model=model,
                instructions=(
                    instructions
                    + "\nReturn only JSON matching this schema:\n"
                    + json.dumps(schema.model_json_schema(), ensure_ascii=False)
                ),
                input=json.dumps(payload, ensure_ascii=False),
            )

        raw = response.output_text.strip()
        try:
            return schema.model_validate_json(raw)
        except Exception as exc:
            raise RuntimeError(
                f"{role} returned invalid structured output: {raw[:1000]}"
            ) from exc

    def text(
        self,
        *,
        model: str,
        instructions: str,
        payload: dict[str, Any],
    ) -> str:
        response = self.client.responses.create(
            model=model,
            instructions=instructions,
            input=json.dumps(payload, ensure_ascii=False),
        )
        return response.output_text.strip()
