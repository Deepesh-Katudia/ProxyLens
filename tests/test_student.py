import json
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.llm.base import LLMError, LLMResponse, Message, Usage
from app.llm.extraction import EXTRACTION_SCHEMA
from app.llm.fallback import extract_with_fallback
from app.llm.local_gguf import LocalGGUFProvider, resolve_gguf_path
from app.llm.prompts import build_extraction_input
from scripts.build_notebooks import FINETUNE, notebook, schema_cell
from scripts.smoke_student import parse_user_message

VALID = json.dumps(
    {
        "item_no": 3,
        "title": "Declare dividend",
        "resolution_type": "DIVIDEND",
        "is_special_resolution": False,
    }
)


class FakeLlama:
    def __init__(self, reply: str = VALID, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "choices": [{"message": {"content": self.reply}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 80},
        }


def _provider(llama: FakeLlama, **kwargs: Any) -> LocalGGUFProvider:
    def factory(**init: Any) -> FakeLlama:
        llama.init_kwargs = init
        return llama

    return LocalGGUFProvider(Path("model.gguf"), llama_factory=factory, **kwargs)


def test_gguf_provider_loads_lazily_and_constrains_to_schema() -> None:
    llama = FakeLlama()
    provider = _provider(llama)
    assert not provider.loaded

    response = provider.generate_json([Message("user", "hi")], EXTRACTION_SCHEMA, "X")

    assert provider.loaded
    assert llama.init_kwargs["n_ctx"] == 4096
    call = llama.calls[0]
    assert call["temperature"] == 0.0
    assert call["response_format"] == {"type": "json_object", "schema": EXTRACTION_SCHEMA}
    assert response.usage == Usage(1200, 80, 0.0)


def test_gguf_provider_can_decode_unconstrained() -> None:
    llama = FakeLlama()
    _provider(llama, constrained=False).generate_json([Message("user", "hi")], {}, "X")

    assert "response_format" not in llama.calls[0]


def test_gguf_provider_wraps_llama_errors() -> None:
    class Broken(FakeLlama):
        def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("context overflow")

    with pytest.raises(LLMError, match="context overflow"):
        _provider(Broken()).generate_json([Message("user", "hi")], {}, "X")


def test_resolve_prefers_local_path(tmp_path: Path) -> None:
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"GGUF")

    assert resolve_gguf_path(Settings(_env_file=None, student_gguf_path=str(gguf))) == gguf
    with pytest.raises(FileNotFoundError):
        resolve_gguf_path(Settings(_env_file=None, student_gguf_path=str(tmp_path / "x.gguf")))


class Scripted:
    def __init__(self, name: str, replies: list[str]) -> None:
        self.name = self.model = name
        self.replies = replies

    def generate_json(
        self, messages: list[Message], schema: dict[str, Any], schema_name: str
    ) -> LLMResponse:
        return LLMResponse(self.replies.pop(0), self.model)


def test_fallback_only_when_student_fails_after_repair() -> None:
    ok = extract_with_fallback(Scripted("s", [VALID]), Scripted("t", []), 3, "x", None)
    assert not ok.used_fallback and ok.outcome.model == "s"

    fell_back = extract_with_fallback(
        Scripted("s", ["{", "{"]), Scripted("t", [VALID]), 3, "x", None
    )
    assert fell_back.used_fallback
    assert fell_back.outcome.model == "t" and fell_back.outcome.valid
    assert not fell_back.student.valid


def test_no_teacher_means_no_fallback() -> None:
    result = extract_with_fallback(Scripted("s", ["{", "{"]), None, 3, "x", None)

    assert not result.used_fallback and not result.outcome.valid


@pytest.mark.parametrize("statement", ["Statement text\nwith lines.", None])
def test_smoke_parser_inverts_prompt_builder(statement: str | None) -> None:
    content = build_extraction_input(7, "To declare dividend.\nRESOLVED THAT ...", statement)

    assert parse_user_message(content) == (7, "To declare dividend.\nRESOLVED THAT ...", statement)


def test_notebook_embeds_repo_schema_and_valid_json() -> None:
    nb = notebook(FINETUNE)
    sources = ["".join(cell["source"]) for cell in nb["cells"]]

    assert schema_cell()[1] in sources
    assert nb["metadata"]["colab"]["gpuType"] == "T4"
    assert json.loads(json.dumps(nb)) == nb
    namespace: dict[str, Any] = {}
    exec(schema_cell()[1], namespace)  # the copied schema is runnable as-is
    assert namespace["ResolutionExtraction"].model_validate_json(VALID).item_no == 3


@pytest.mark.parametrize(
    ("path", "cells_name"),
    [
        ("notebooks/01_finetune_qlora.ipynb", "FINETUNE"),
        ("notebooks/02_eval_student.ipynb", "EVAL"),
    ],
)
def test_committed_notebooks_are_up_to_date(path: str, cells_name: str) -> None:
    import scripts.build_notebooks as builder

    expected = json.dumps(notebook(getattr(builder, cells_name)), indent=1) + "\n"
    assert Path(path).read_text(encoding="utf-8") == expected, (
        "run: python -m scripts.build_notebooks"
    )
