"""OpenRouter chat-completions provider (OpenAI-compatible API) for the teacher."""

import logging
import time
from typing import Any

import httpx

from app.llm.base import LLMError, LLMResponse, Message, Usage

logger = logging.getLogger(__name__)

REPO_URL = "https://github.com/Deepesh-Katudia/ProxyLens"
TIMEOUT_S = 180
MAX_ATTEMPTS = 6  # waits 2+4+8+16+32 s, about a minute, before giving up
BACKOFF_BASE_S = 2.0
MAX_RETRY_AFTER_S = 120.0
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds from a Retry-After header (capped), if the server sent one."""
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_S)


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        *,
        max_output_tokens: int = 2048,
        structured: bool = True,
        reasoning_effort: str | None = "low",
        client: httpx.Client | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        if not model:
            raise ValueError("TEACHER_MODEL is not set")
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.structured = structured
        self.reasoning_effort = reasoning_effort
        self._sleep = sleep
        self._client = client or httpx.Client(timeout=TIMEOUT_S)
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": REPO_URL,
            "X-Title": "ProxyLens",
        }

    def _payload(
        self, messages: list[Message], schema: dict[str, Any], schema_name: str
    ) -> dict[str, Any]:
        response_format: dict[str, Any] = (
            {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
            if self.structured
            else {"type": "json_object"}
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
            "response_format": response_format,
            "usage": {"include": True},  # OpenRouter returns the billed cost
        }
        if self.reasoning_effort:
            # Thinking models bill hidden reasoning tokens; extraction needs little.
            payload["reasoning"] = {"effort": self.reasoning_effort, "exclude": True}
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            retry_after: float | None = None
            try:
                response = self._client.post(self._url, json=payload, headers=self._headers)
            except httpx.HTTPError as exc:
                error: str = f"network error: {exc}"
            else:
                if response.status_code == httpx.codes.OK:
                    body: dict[str, Any] = response.json()
                    if "error" not in body:
                        return body
                    error = f"API error: {body['error']}"
                elif response.status_code in RETRY_STATUSES:
                    error = f"HTTP {response.status_code}"
                    retry_after = _retry_after(response)
                else:
                    raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")
            if attempt == MAX_ATTEMPTS:
                raise LLMError(f"gave up after {attempt} attempts: {error}")
            delay = retry_after or BACKOFF_BASE_S * 2 ** (attempt - 1)
            logger.warning("OpenRouter %s; retrying in %.0fs", error, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")

    def generate_json(
        self, messages: list[Message], schema: dict[str, Any], schema_name: str
    ) -> LLMResponse:
        started = time.monotonic()
        body = self._post(self._payload(messages, schema, schema_name))
        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"malformed response: {str(body)[:300]}") from exc
        usage = body.get("usage") or {}
        return LLMResponse(
            text=text,
            model=body.get("model", self.model),
            usage=Usage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                cost_usd=float(usage.get("cost", 0.0)),
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
