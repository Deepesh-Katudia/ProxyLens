"""Label agenda items with the teacher LLM (SPEC 7.2 step 3).

    uv run python -m scripts.teacher_label --dry-run            # estimate cost, no calls
    uv run python -m scripts.teacher_label --budget-usd 5       # label until $5 is spent
    uv run python -m scripts.teacher_label --model <id> --limit 20

Appends to data/processed/teacher_labels.jsonl and resumes where it left off
(items already labelled by the same model are skipped). Items from companies in
the gold split are never sent to the teacher: they are reserved for human labels.
"""

import argparse
import logging
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.dataset.jsonl import append_jsonl, read_jsonl
from app.dataset.split import Split, assign_split
from app.llm.base import LLMProvider
from app.llm.extraction import extract
from app.llm.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_input
from app.llm.providers import create_teacher
from scripts.segment import ITEMS_JSONL

logger = logging.getLogger("teacher_label")

LABELS_JSONL = Path("data/processed/teacher_labels.jsonl")
MODELS_URL = "https://openrouter.ai/api/v1/models"
CHARS_PER_TOKEN = 4  # rough estimate for English legal text
EST_OUTPUT_TOKENS = 600  # JSON answer plus low-effort reasoning
DEFAULT_BUDGET_USD = 5.0


def pending_items(model: str, limit: int | None) -> list[dict[str, Any]]:
    # Done = the model replied (valid or not). Provider failures such as rate
    # limits produced no reply and are retried on the next run.
    done = {
        r["item_id"]
        for r in read_jsonl(LABELS_JSONL)
        if r.get("label_model") == model and (r.get("valid") or r.get("raw_outputs"))
    }
    pending: list[dict[str, Any]] = []
    skipped_gold = skipped_unnamed = 0
    for item in read_jsonl(ITEMS_JSONL):
        if item["item_id"] in done:
            continue
        if not item.get("company"):
            skipped_unnamed += 1
            continue
        if assign_split(item["company"]) is Split.GOLD:
            skipped_gold += 1
            continue
        pending.append(item)
    logger.info(
        "%d to label; skipped %d already done, %d gold-split, %d without company",
        len(pending), len(done), skipped_gold, skipped_unnamed,
    )  # fmt: skip
    return pending[:limit] if limit else pending


def estimate_cost(items: list[dict[str, Any]], model: str) -> float:
    """Rough cost from OpenRouter's public price list (USD per token)."""
    pricing = next(
        m["pricing"] for m in httpx.get(MODELS_URL, timeout=60).json()["data"] if m["id"] == model
    )
    prompt_chars = sum(
        len(EXTRACTION_SYSTEM_PROMPT)
        + len(build_extraction_input(i["item_no"], i["text"], i.get("explanatory_statement")))
        for i in items
    )
    prompt_tokens = prompt_chars / CHARS_PER_TOKEN
    completion_tokens = EST_OUTPUT_TOKENS * len(items)
    return prompt_tokens * float(pricing["prompt"]) + completion_tokens * float(
        pricing["completion"]
    )


def _label(provider: LLMProvider, item: dict[str, Any]) -> dict[str, Any]:
    outcome = extract(provider, item["item_no"], item["text"], item.get("explanatory_statement"))
    return {"item_id": item["item_id"], "label_model": provider.model, **outcome.to_record()}


def run(provider: LLMProvider, items: list[dict[str, Any]], budget: float, workers: int) -> None:
    spent = 0.0
    labelled = valid = 0

    def batches() -> Iterator[list[dict[str, Any]]]:
        for start in range(0, len(items), workers):
            yield items[start : start + workers]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for batch in batches():
            if spent >= budget:
                logger.warning("Budget of $%.2f reached; stopping", budget)
                break
            for record in pool.map(lambda it: _label(provider, it), batch):
                append_jsonl(LABELS_JSONL, record)
                spent += record["cost_usd"]
                labelled += 1
                valid += record["valid"]
            logger.info("labelled %d/%d, valid %d, spent $%.4f", labelled, len(items), valid, spent)
    logger.info("Done: %d labelled, %d valid, $%.4f spent", labelled, valid, spent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="OpenRouter model id (default: TEACHER_MODEL)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = get_settings()
    model = args.model or settings.teacher_model
    if not model:
        raise SystemExit("set TEACHER_MODEL in .env or pass --model")
    items = pending_items(model, args.limit)
    if args.dry_run:
        logger.info("Estimated cost for %d items on %s: $%.2f", len(items), model,
                    estimate_cost(items, model))  # fmt: skip
        return 0
    run(create_teacher(settings, model), items, args.budget_usd, args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
