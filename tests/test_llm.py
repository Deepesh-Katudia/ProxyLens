import json
from typing import Any

import httpx
import pytest

from app.llm.base import LLMError, LLMResponse, Message, Usage
from app.llm.extraction import EXTRACTION_SCHEMA, extract, validate
from app.llm.openrouter import OpenRouterProvider
from app.llm.prompts import MAX_STATEMENT_CHARS, TRUNCATION_MARK, build_extraction_input
from app.llm.schema import parse_json_object, strict_json_schema
from app.schemas.resolution import ResolutionExtraction, ResolutionType

VALID = {
    "item_no": 6,
    "title": "Re-appoint Mr. A as Independent Director",
    "resolution_type": "INDEPENDENT_DIRECTOR_APPOINT",
    "is_special_resolution": True,
    "persons": [
        {
            "name": "Mr. A",
            "role": "Independent Director",
            "age": 64,
            "din": "01234567",
            "is_promoter": False,
            "tenure_years_proposed": 5,
            "prior_tenure_years": 5,
            "board_attendance_pct": 100,
        }
    ],
    "amounts": [],
    "counterparty": None,
    "counterparty_is_related": None,
    "transaction_nature": None,
    "duration_years": 5,
    "key_facts": ["Second term of five years"],
}


# --- schema helpers ----------------------------------------------------------


def _objects(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for value in node.values():
            found += _objects(value)
    elif isinstance(node, list):
        for value in node:
            found += _objects(value)
    return found


def test_strict_schema_inlines_refs_and_requires_every_property() -> None:
    schema = strict_json_schema(ResolutionExtraction)

    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    for obj in _objects(schema):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
    assert "default" not in json.dumps(schema)
    # Regression: a *property* named "title" must survive keyword stripping.
    assert "title" in schema["properties"] and "title" in schema["required"]
    assert "name" in schema["properties"]["persons"]["items"]["properties"]


@pytest.mark.parametrize(
    "text",
    [
        json.dumps(VALID),
        "```json\n" + json.dumps(VALID) + "\n```",
        "Here is the JSON:\n" + json.dumps(VALID) + "\nDone.",
    ],
)
def test_parse_json_object_tolerates_fences_and_prose(text: str) -> None:
    assert parse_json_object(text)["item_no"] == 6


def test_parse_json_object_rejects_non_objects() -> None:
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]")


def test_validate_reports_schema_errors() -> None:
    with pytest.raises(ValueError, match="resolution_type"):
        validate(json.dumps({**VALID, "resolution_type": "DIVIDENDS"}))


def test_prompt_truncates_long_statements() -> None:
    prompt = build_extraction_input(4, "To appoint Mr. A.", "x" * (MAX_STATEMENT_CHARS + 500))

    assert prompt.endswith(TRUNCATION_MARK)
    assert prompt.startswith("AGENDA ITEM No. 4:")
    assert "(none)" in build_extraction_input(2, "To declare dividend.", None)


# --- OpenRouter provider -----------------------------------------------------


def _completion(content: str, cost: float = 0.0012) -> dict[str, Any]:
    return {
        "model": "google/gemini-3.8-flash",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 300, "cost": cost},
    }


def _provider(handler: Any) -> tuple[OpenRouterProvider, list[float]]:
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenRouterProvider(
        "sk-test", "google/gemini-3.8-flash", client=client, sleep=sleeps.append
    )
    return provider, sleeps


def test_openrouter_sends_strict_schema_and_reads_cost() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(200, json=_completion(json.dumps(VALID)))

    provider, _ = _provider(handler)
    response = provider.generate_json([Message("user", "hi")], EXTRACTION_SCHEMA, "X")

    payload = seen[0]
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["temperature"] == 0
    assert payload["usage"] == {"include": True}
    assert payload["reasoning"] == {"effort": "low", "exclude": True}
    assert response.usage == Usage(900, 300, 0.0012)


def test_openrouter_retries_rate_limits_then_succeeds() -> None:
    statuses = iter([429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(status, json=_completion("{}") if status == 200 else {})

    provider, sleeps = _provider(handler)
    provider.generate_json([Message("user", "hi")], {}, "X")

    assert sleeps == [2.0, 4.0]


def test_openrouter_honours_retry_after() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "7"}, json={}),
            httpx.Response(200, json=_completion("{}")),
        ]
    )
    provider, sleeps = _provider(lambda request: next(responses))

    provider.generate_json([Message("user", "hi")], {}, "X")

    assert sleeps == [7.0]


def test_openrouter_does_not_retry_client_errors() -> None:
    provider, sleeps = _provider(lambda request: httpx.Response(400, text="bad model"))

    with pytest.raises(LLMError, match="400"):
        provider.generate_json([Message("user", "hi")], {}, "X")
    assert sleeps == []


def test_openrouter_requires_key_and_model() -> None:
    with pytest.raises(ValueError):
        OpenRouterProvider("", "some/model")
    with pytest.raises(ValueError):
        OpenRouterProvider("sk", "")


# --- extraction with repair --------------------------------------------------


class ScriptedProvider:
    name = "fake"
    model = "fake/teacher"

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = replies
        self.calls: list[list[Message]] = []

    def generate_json(
        self, messages: list[Message], schema: dict[str, Any], schema_name: str
    ) -> LLMResponse:
        self.calls.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(reply, self.model, Usage(100, 50, 0.001), 10)


def test_extract_valid_on_first_try() -> None:
    outcome = extract(ScriptedProvider([json.dumps(VALID)]), 6, "item text", "statement")

    assert outcome.valid and outcome.valid_first_try
    assert outcome.extraction is not None
    assert outcome.extraction.resolution_type is ResolutionType.INDEPENDENT_DIRECTOR_APPOINT


def test_extract_repairs_once_and_sends_the_error_back() -> None:
    provider = ScriptedProvider(["{not json", json.dumps(VALID)])

    outcome = extract(provider, 6, "item text", None)

    assert outcome.valid and not outcome.valid_first_try
    assert outcome.attempts == 2
    assert outcome.usage == Usage(200, 100, 0.002)
    repair = provider.calls[1][-1]
    assert repair.role == "user" and "not valid" in repair.content


def test_extract_gives_up_after_one_repair() -> None:
    outcome = extract(ScriptedProvider(["{}", "{}"]), 6, "item text", None)

    assert not outcome.valid
    assert outcome.attempts == 2
    assert outcome.error is not None
    assert outcome.to_record()["extraction"] is None


def test_extract_records_provider_failure() -> None:
    outcome = extract(ScriptedProvider([LLMError("HTTP 500")]), 6, "item text", None)

    assert not outcome.valid
    assert outcome.error is not None and "HTTP 500" in outcome.error
