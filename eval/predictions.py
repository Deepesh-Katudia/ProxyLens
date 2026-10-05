"""Prediction files: `eval/results/<run_id>.json` (format in eval/README.md).

Written by `eval.run` (API and local GGUF models) and by notebook 02 (base and
fine-tuned 3B on a GPU). Metrics are computed from these files by `eval.report`.
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

RESULTS_DIR = Path("eval/results")


class PredictionItem(BaseModel):
    item_id: str
    output_text: str  # the model's first reply, before any repair
    latency_ms: int = 0
    output_tokens: int = 0
    # Only from eval.run (the notebook does no repair): whether the reply was valid
    # after the one repair retry. False means the pipeline would fall back to the teacher.
    valid_after_repair: bool | None = None
    cost_usd: float | None = None


class Decoding(BaseModel):
    greedy: bool = True
    max_new_tokens: int = 1024
    constrained: bool = False


class PredictionRun(BaseModel):
    run_id: str
    provider: str  # base_hf | finetuned_lora | local_gguf | teacher | openrouter
    model: str
    split: str
    created_at: str
    hardware: str = ""
    decoding: Decoding = Field(default_factory=Decoding)
    items: list[PredictionItem]


def save_run(run: PredictionRun, results_dir: Path = RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{run.run_id}.json"
    path.write_text(run.model_dump_json(indent=1), encoding="utf-8")
    return path


def load_runs(results_dir: Path = RESULTS_DIR, split: str = "test") -> list[PredictionRun]:
    """Every run for a split; when a model has several runs, only the newest is kept."""
    runs = [
        PredictionRun.model_validate(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted(results_dir.glob("*.json"))
    ]
    latest: dict[tuple[str, str], PredictionRun] = {}
    for run in sorted((r for r in runs if r.split == split), key=lambda r: r.created_at):
        latest[(run.provider, run.model)] = run
    return list(latest.values())
