"""Fine-tuned student served locally from a GGUF file with llama.cpp (SPEC 3)."""

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import Settings
from app.llm.base import LLMError, LLMResponse, Message, Usage

logger = logging.getLogger(__name__)

# Longest SFT example is ~4,100 tokens (prompt + answer) with the Qwen tokenizer.
DEFAULT_N_CTX = 4096
DEFAULT_MAX_TOKENS = 1024

LlamaFactory = Callable[..., Any]


def _default_llama_factory(**kwargs: Any) -> Any:
    try:
        from llama_cpp import Llama
    except ImportError as exc:  # optional extra
        raise LLMError("llama-cpp-python is not installed; run `uv sync --extra student`") from exc
    return Llama(**kwargs)


def resolve_gguf_path(settings: Settings) -> Path:
    """A local GGUF if configured, otherwise the file downloaded (and cached) from HF Hub."""
    if settings.student_gguf_path:
        path = Path(settings.student_gguf_path)
        if not path.is_file():
            raise FileNotFoundError(f"STUDENT_GGUF_PATH does not exist: {path}")
        return path
    from huggingface_hub import hf_hub_download

    token = settings.hf_token.get_secret_value() or None
    logger.info(
        "Fetching %s/%s from HF Hub", settings.student_gguf_repo, settings.student_gguf_file
    )
    return Path(
        hf_hub_download(settings.student_gguf_repo, settings.student_gguf_file, token=token)
    )


class LocalGGUFProvider:
    name = "local_gguf"

    def __init__(
        self,
        model_path: Path,
        *,
        model_name: str | None = None,
        n_ctx: int = DEFAULT_N_CTX,
        n_threads: int | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        constrained: bool = True,
        llama_factory: LlamaFactory = _default_llama_factory,
    ) -> None:
        self.model_path = model_path
        self.model = model_name or model_path.stem
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.max_tokens = max_tokens
        self.constrained = constrained  # grammar-constrained JSON decoding
        self._factory = llama_factory
        self._llm: Any = None
        self._lock = threading.Lock()  # llama.cpp contexts are not thread-safe

    def _load(self) -> Any:
        if self._llm is None:
            logger.info("Loading GGUF %s (n_ctx=%d)", self.model_path, self.n_ctx)
            self._llm = self._factory(
                model_path=str(self.model_path),
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                verbose=False,
            )
        return self._llm

    @property
    def loaded(self) -> bool:
        return self._llm is not None

    def generate_json(
        self, messages: list[Message], schema: dict[str, Any], schema_name: str
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": 0.0,
            "max_tokens": self.max_tokens,
        }
        if self.constrained:
            kwargs["response_format"] = {"type": "json_object", "schema": schema}
        started = time.monotonic()
        with self._lock:
            try:
                result = self._load().create_chat_completion(**kwargs)
            except LLMError:
                raise
            except Exception as exc:  # llama.cpp raises plain RuntimeError/ValueError
                raise LLMError(f"local inference failed: {exc}") from exc
        try:
            text = result["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"malformed llama.cpp response: {str(result)[:300]}") from exc
        usage = result.get("usage") or {}
        return LLMResponse(
            text=text,
            model=self.model,
            usage=Usage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
