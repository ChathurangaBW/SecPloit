from __future__ import annotations

import json
from types import SimpleNamespace

from pydantic import BaseModel

from app.config import Settings
from app.llm import OpenAIResponsesLLM


class ResultSchema(BaseModel):
    value: str


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **request):
        self.calls.append(request)
        if request.get("text"):
            return SimpleNamespace(output_text=json.dumps({"value": "ok"}))
        return SimpleNamespace(output_text="report")


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_structured_request_uses_high_reasoning_and_private_storage() -> None:
    config = Settings(
        OPENAI_API_KEY="test",
        OPENAI_MODEL="gpt-5.6",
        OPENAI_REASONING_EFFORT="high",
        OPENAI_MAX_OUTPUT_TOKENS=12000,
        OPENAI_STORE_RESPONSES=False,
    )
    client = FakeClient()
    llm = OpenAIResponsesLLM(config=config, client=client)

    result = llm.structured(
        model="gpt-5.6",
        role="plan",
        instructions="Plan carefully.",
        payload={"target": "dvwa"},
        schema=ResultSchema,
    )

    assert result.value == "ok"
    request = client.responses.calls[0]
    assert request["reasoning"] == {"effort": "high"}
    assert request["max_output_tokens"] == 12000
    assert request["store"] is False
    assert request["text"]["format"]["strict"] is True


def test_operator_can_use_separate_reasoning_effort() -> None:
    config = Settings(
        OPENAI_API_KEY="test",
        OPENAI_OPERATOR_REASONING_EFFORT="medium",
    )
    client = FakeClient()
    llm = OpenAIResponsesLLM(config=config, client=client)

    llm.structured(
        model="gpt-5.6",
        role="operator",
        instructions="Choose an action.",
        payload={},
        schema=ResultSchema,
    )

    assert client.responses.calls[0]["reasoning"] == {"effort": "medium"}


def test_text_request_uses_critic_effort() -> None:
    config = Settings(
        OPENAI_API_KEY="test",
        OPENAI_CRITIC_REASONING_EFFORT="xhigh",
    )
    client = FakeClient()
    llm = OpenAIResponsesLLM(config=config, client=client)

    result = llm.text(
        model="gpt-5.6",
        role="report",
        instructions="Write the report.",
        payload={"finding": "none"},
    )

    assert result == "report"
    assert client.responses.calls[0]["reasoning"] == {"effort": "xhigh"}


def test_max_reasoning_and_pro_mode_are_sent_together() -> None:
    config = Settings(
        OPENAI_API_KEY="test",
        OPENAI_REASONING_MODE="pro",
        OPENAI_REASONING_EFFORT="max",
    )
    client = FakeClient()
    llm = OpenAIResponsesLLM(config=config, client=client)

    llm.structured(
        model="gpt-5.6",
        role="plan",
        instructions="Use the quality-first configuration.",
        payload={},
        schema=ResultSchema,
    )

    assert client.responses.calls[0]["reasoning"] == {
        "effort": "max",
        "mode": "pro",
    }
