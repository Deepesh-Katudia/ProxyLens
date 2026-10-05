"""Pre-fill gold candidates with a model draft for the labeller to review.

    uv run python -m scripts.draft_gold [--model anthropic/claude-sonnet-5.5] [--workers 4]

Drafts go to data/gold/drafts.jsonl (gitignored, never uploaded) and are only a
starting point: an item counts as gold once a person has checked it on /label
and saved it, which records `draft_model` on the label. The drafting model is
deliberately not the teacher, so drafts don't nudge the gold set towards the
teacher's answers. Resumable: items that already have a draft are skipped.
"""

import argparse
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.dataset.jsonl import append_jsonl, read_jsonl
from app.gold.store import DEFAULT_CANDIDATES, DEFAULT_DRAFTS
from app.llm.base import Usage
from app.llm.extraction import extract
from app.llm.openrouter import OpenRouterProvider

logger = logging.getLogger("draft_gold")

DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"


@dataclass
class Tally:
    ok: int = 0
    failed: int = 0
    usage: Usage = field(default_factory=Usage)


def pending(candidates: Path, drafts: Path) -> list[dict[str, Any]]:
    done = {row["item_id"] for row in read_jsonl(drafts)} if drafts.exists() else set()
    return [c for c in read_jsonl(candidates) if c["item_id"] not in done]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = get_settings()
    teacher = settings.teacher_model
    if args.model == teacher:
        # Drafting with the teacher would bias gold towards the teacher's answers.
        raise SystemExit(f"--model must not be the teacher ({teacher})")
    provider = OpenRouterProvider(
        api_key=settings.openrouter_api_key.get_secret_value(),
        model=args.model,
        base_url=settings.openrouter_base_url,
        max_output_tokens=settings.teacher_max_output_tokens,
        structured=True,
    )
    todo = pending(DEFAULT_CANDIDATES, DEFAULT_DRAFTS)[: args.limit]
    logger.info("%d items to draft with %s", len(todo), args.model)

    lock = threading.Lock()
    tally = Tally()

    def draft(candidate: dict[str, Any]) -> None:
        outcome = extract(
            provider,
            candidate["item_no"],
            candidate["text"],
            candidate.get("explanatory_statement"),
        )
        with lock:
            tally.usage = tally.usage + outcome.usage
            if outcome.extraction is None:
                tally.failed += 1
                logger.warning("%s: no valid draft (%s)", candidate["item_id"], outcome.error)
                return
            append_jsonl(
                DEFAULT_DRAFTS,
                {
                    "item_id": candidate["item_id"],
                    "model": outcome.model,
                    "extraction": outcome.extraction.model_dump(mode="json"),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            tally.ok += 1
            done = tally.ok + tally.failed
            if done % 20 == 0:
                logger.info("%d/%d drafted", done, len(todo))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(draft, todo))

    usage = tally.usage
    print(
        f"drafted {tally.ok}, failed {tally.failed}, "
        f"tokens {usage.prompt_tokens:,} in / {usage.completion_tokens:,} out, "
        f"cost ${usage.cost_usd:.2f}"
    )
    return 0 if not tally.failed else 1


if __name__ == "__main__":
    sys.exit(main())
