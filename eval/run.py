"""Run an extraction model over the gold-split items and save raw predictions.

    uv run python -m eval.run --provider teacher
    uv run python -m eval.run --provider openrouter --model qwen/qwen-2.5-7b-instruct
    uv run python -m eval.run --provider gguf [--gguf-path model.gguf] [--name finetuned_gguf]

Writes eval/results/<run_id>.json (eval/README.md). Each item records the first
reply (JSON validity is measured before repair) and whether it was valid after the
one repair retry (the fallback rate). Re-running the same command resumes.
Base and fine-tuned 3B on a GPU come from notebooks/02_eval_student.ipynb instead.
"""

import argparse
import logging
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.dataset.jsonl import read_jsonl
from app.gold.store import DEFAULT_CANDIDATES
from app.llm.base import LLMProvider
from app.llm.extraction import extract
from app.llm.local_gguf import LocalGGUFProvider, resolve_gguf_path
from app.llm.openrouter import OpenRouterProvider
from app.llm.providers import create_teacher
from eval.predictions import RESULTS_DIR, Decoding, PredictionItem, PredictionRun, save_run

logger = logging.getLogger("eval.run")
SAVE_EVERY = 10


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_provider(args: argparse.Namespace) -> tuple[str, LLMProvider, bool]:
    """(provider name for the results, provider, grammar-constrained?)"""
    settings = get_settings()
    if args.provider == "teacher":
        return "teacher", create_teacher(settings), False
    if args.provider == "openrouter":
        if not args.model:
            raise SystemExit("--provider openrouter needs --model")
        provider = OpenRouterProvider(
            api_key=settings.openrouter_api_key.get_secret_value(),
            model=args.model,
            base_url=settings.openrouter_base_url,
            max_output_tokens=settings.teacher_max_output_tokens,
            structured=False,  # small open models: plain JSON mode, judged like the 3B
            reasoning_effort=None,
        )
        return "openrouter", provider, False
    path = Path(args.gguf_path) if args.gguf_path else resolve_gguf_path(settings)
    gguf = LocalGGUFProvider(
        path,
        model_name=args.model or path.stem,
        n_threads=settings.student_n_threads,
        constrained=not args.unconstrained,
    )
    return args.name or "local_gguf", gguf, gguf.constrained


def load_existing(path: Path) -> dict[str, PredictionItem]:
    if not path.exists():
        return {}
    run = PredictionRun.model_validate_json(path.read_text(encoding="utf-8"))
    return {item.item_id: item for item in run.items}


def predict(provider: LLMProvider, candidate: dict[str, Any]) -> PredictionItem:
    outcome = extract(
        provider, candidate["item_no"], candidate["text"], candidate.get("explanatory_statement")
    )
    return PredictionItem(
        item_id=candidate["item_id"],
        output_text=outcome.raw_outputs[0] if outcome.raw_outputs else "",
        latency_ms=outcome.latency_ms,
        output_tokens=outcome.usage.completion_tokens,
        valid_after_repair=outcome.valid,
        cost_usd=outcome.usage.cost_usd if isinstance(provider, OpenRouterProvider) else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["teacher", "openrouter", "gguf"], required=True)
    parser.add_argument("--model", help="OpenRouter model id, or a display name for a GGUF")
    parser.add_argument("--gguf-path", help="local GGUF; default: STUDENT_GGUF_* from .env")
    parser.add_argument("--name", help="provider name in results, e.g. base_gguf")
    parser.add_argument("--unconstrained", action="store_true", help="GGUF without JSON grammar")
    parser.add_argument("--workers", type=int, default=4, help="parallel API calls")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    name, provider, constrained = build_provider(args)
    stamp = datetime.now(UTC)
    run_id = args.run_id or f"{stamp:%Y-%m-%d}_{name}_{slug(provider.model)}_test"
    path = RESULTS_DIR / f"{run_id}.json"
    done = load_existing(path)
    candidates = list(read_jsonl(DEFAULT_CANDIDATES))[: args.limit]
    todo = [c for c in candidates if c["item_id"] not in done]
    logger.info("%s: %d items (%d already done) -> %s", provider.model, len(todo), len(done), path)

    hardware = "local CPU (llama.cpp)" if args.provider == "gguf" else "OpenRouter API"
    lock = threading.Lock()

    def save() -> None:
        ordered = [done[c["item_id"]] for c in candidates if c["item_id"] in done]
        save_run(
            PredictionRun(
                run_id=run_id,
                provider=name,
                model=provider.model,
                split="test",
                created_at=stamp.isoformat(),
                hardware=hardware,
                decoding=Decoding(constrained=constrained),
                items=ordered,
            )
        )

    def work(candidate: dict[str, Any]) -> None:
        item = predict(provider, candidate)
        with lock:
            done[item.item_id] = item
            if len(done) % SAVE_EVERY == 0:
                save()
                logger.info("%d/%d", len(done), len(candidates))

    workers = 1 if args.provider == "gguf" else args.workers  # llama.cpp: one context
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, todo))
    save()
    valid = sum(1 for i in done.values() if i.valid_after_repair)
    print(f"saved {path}: {len(done)} items, {valid} valid after repair")
    return 0


if __name__ == "__main__":
    sys.exit(main())
