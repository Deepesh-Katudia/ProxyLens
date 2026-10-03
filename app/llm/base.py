"""Provider-agnostic LLM interface (SPEC 3: `generate_json(prompt, schema)`)."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            self.cost_usd + other.cost_usd,
        )


@dataclass(frozen=True)
class LLMResponse:
    text: str  # raw model output
    model: str  # model that actually served the request
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0


class LLMError(RuntimeError):
    """The provider failed to return a response (network, HTTP or API error)."""


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(
        self, messages: list[Message], schema: dict[str, Any], schema_name: str
    ) -> LLMResponse:
        """Ask for a JSON object matching `schema`; returns the raw text."""
        ...
