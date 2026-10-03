"""Resolution extraction: call a provider, validate, repair once (SPEC 5.1)."""

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.llm.base import LLMError, LLMProvider, Message, Usage
from app.llm.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_input, repair_message
from app.llm.schema import parse_json_object, strict_json_schema
from app.schemas.resolution import ResolutionExtraction

SCHEMA_NAME = "ResolutionExtraction"
EXTRACTION_SCHEMA = strict_json_schema(ResolutionExtraction)
MAX_ATTEMPTS = 2  # first try + one repair


@dataclass(frozen=True)
class ExtractionOutcome:
    extraction: ResolutionExtraction | None
    raw_outputs: tuple[str, ...]  # every model reply, in order
    attempts: int
    valid_first_try: bool  # SPEC 8: JSON validity before repair
    error: str | None
    model: str
    usage: Usage
    latency_ms: int

    @property
    def valid(self) -> bool:
        return self.extraction is not None

    def to_record(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "valid_first_try": self.valid_first_try,
            "attempts": self.attempts,
            "error": self.error,
            "model": self.model,
            "extraction": self.extraction.model_dump(mode="json") if self.extraction else None,
            "raw_outputs": list(self.raw_outputs),
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "cost_usd": self.usage.cost_usd,
            "latency_ms": self.latency_ms,
        }


def validate(text: str) -> ResolutionExtraction:
    """Parse and validate one model reply; raises ValueError with a readable reason."""
    try:
        return ResolutionExtraction.model_validate(parse_json_object(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def extract(
    provider: LLMProvider, item_no: int, item_text: str, explanatory_statement: str | None
) -> ExtractionOutcome:
    messages = [
        Message("system", EXTRACTION_SYSTEM_PROMPT),
        Message("user", build_extraction_input(item_no, item_text, explanatory_statement)),
    ]
    outputs: list[str] = []
    usage = Usage()
    latency = 0
    model = provider.model
    error: str | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = provider.generate_json(messages, EXTRACTION_SCHEMA, SCHEMA_NAME)
        except LLMError as exc:
            error = f"provider error: {exc}"
            break
        outputs.append(response.text)
        usage += response.usage
        latency += response.latency_ms
        model = response.model
        try:
            extraction = validate(response.text)
        except ValueError as exc:
            error = str(exc)
            messages += [
                Message("assistant", response.text),
                Message("user", repair_message(error)),
            ]
            continue
        return ExtractionOutcome(
            extraction, tuple(outputs), attempt, attempt == 1, None, model, usage, latency
        )

    return ExtractionOutcome(
        None, tuple(outputs), len(outputs), False, error, model, usage, latency
    )
