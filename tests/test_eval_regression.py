"""SPEC 8 regression gate: the fine-tuned model must not lose more than 2 points of
JSON validity or type macro-F1 against eval/baseline.json.

Runs the real GGUF on CPU (about a minute per item), so it is opt-in:
    PROXYLENS_MODEL_TESTS=1 uv run pytest tests/test_eval_regression.py
and skips when the model file, the baseline or the local reference labels are missing.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config import Settings
from app.dataset.jsonl import read_jsonl
from app.gold.store import DEFAULT_CANDIDATES, DEFAULT_LABELS
from app.llm.local_gguf import LocalGGUFProvider
from eval.baseline import BASELINE
from eval.metrics import score_run
from eval.predictions import PredictionRun
from eval.reference import load_reference
from eval.run import predict

TOLERANCE = 0.02  # 2 points


def _gguf_path() -> Path | None:
    settings = Settings()
    if settings.student_gguf_path:
        path = Path(settings.student_gguf_path)
        return path if path.is_file() else None
    from huggingface_hub import try_to_load_from_cache

    cached = try_to_load_from_cache(settings.student_gguf_repo, settings.student_gguf_file)
    return Path(cached) if isinstance(cached, str) else None


@pytest.mark.skipif(os.environ.get("PROXYLENS_MODEL_TESTS") != "1", reason="opt-in: slow")
def test_finetuned_model_has_not_regressed() -> None:
    model = _gguf_path()
    if model is None:
        pytest.skip("fine-tuned GGUF not present locally")
    if not BASELINE.exists() or not DEFAULT_LABELS.exists():
        pytest.skip("eval/baseline.json or local reference labels missing")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    wanted = set(baseline["item_ids"])
    candidates = [c for c in read_jsonl(DEFAULT_CANDIDATES) if c["item_id"] in wanted]
    provider = LocalGGUFProvider(model, constrained=baseline["constrained"])

    run = PredictionRun(
        run_id="regression",
        provider="finetuned_gguf",
        model=model.stem,
        split="test",
        created_at=datetime.now(UTC).isoformat(),
        items=[predict(provider, c) for c in candidates],
    )
    metrics = score_run(run, load_reference().labels)

    assert metrics.json_valid >= baseline["json_valid"] - TOLERANCE
    assert metrics.type_macro_f1 >= baseline["type_macro_f1"] - TOLERANCE
