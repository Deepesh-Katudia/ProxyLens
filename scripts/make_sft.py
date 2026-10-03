"""Build SFT data from validated teacher labels (SPEC 7.2 steps 4, 6, 7).

    uv run python -m scripts.make_sft --model <teacher id>
    uv run python -m scripts.make_sft --model <id> --agree-with <second id>

Writes data/sft/{train,val}.jsonl (chat format, grouped by company),
data/gold/candidates.jsonl (items from gold-split companies, for human
labelling) and data/sft/stats.json for the dataset card.
"""

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from app.dataset.jsonl import read_jsonl, write_jsonl
from app.dataset.sft import sft_record
from app.dataset.split import Split, assign_split
from app.schemas.resolution import ResolutionExtraction
from scripts.segment import ITEMS_JSONL
from scripts.teacher_label import LABELS_JSONL

logger = logging.getLogger("make_sft")

SFT_DIR = Path("data/sft")
GOLD_CANDIDATES = Path("data/gold/candidates.jsonl")


def valid_labels(model: str) -> dict[str, ResolutionExtraction]:
    """Latest valid label per item from one teacher model."""
    labels: dict[str, ResolutionExtraction] = {}
    for row in read_jsonl(LABELS_JSONL):
        if row.get("label_model") == model and row.get("valid"):
            labels[row["item_id"]] = ResolutionExtraction.model_validate(row["extraction"])
    return labels


def build(
    items: list[dict[str, Any]],
    labels: dict[str, ResolutionExtraction],
    second: dict[str, ResolutionExtraction] | None,
) -> tuple[dict[Split, list[dict[str, Any]]], dict[str, Any]]:
    out: dict[Split, list[dict[str, Any]]] = {s: [] for s in Split}
    stats: Counter[str] = Counter()
    types: dict[str, Counter[str]] = {s.value: Counter() for s in (Split.TRAIN, Split.VAL)}
    companies: dict[str, set[str]] = {s.value: set() for s in Split}

    for item in items:
        if not item.get("company"):
            stats["skipped_no_company"] += 1
            continue
        split = assign_split(item["company"])
        companies[split.value].add(item["company"])
        if split is Split.GOLD:
            out[split].append(item)  # never teacher-labelled
            continue
        label = labels.get(item["item_id"])
        if label is None:
            stats["skipped_unlabelled_or_invalid"] += 1
            continue
        if second is not None:
            other = second.get(item["item_id"])
            if other is None or other.resolution_type != label.resolution_type:
                stats["dropped_teacher_disagreement"] += 1
                continue
        out[split].append(
            sft_record(item["item_no"], item["text"], item.get("explanatory_statement"), label)
        )
        types[split.value][label.resolution_type.value] += 1

    summary = {
        "counts": {s.value: len(rows) for s, rows in out.items()},
        "companies": {k: len(v) for k, v in companies.items()},
        "resolution_types": {k: dict(v.most_common()) for k, v in types.items()},
        "filtering": dict(stats),
    }
    return out, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="teacher model whose labels to use")
    parser.add_argument("--agree-with", help="keep only items where this model agrees on type")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    items = list(read_jsonl(ITEMS_JSONL))
    second = valid_labels(args.agree_with) if args.agree_with else None
    splits, summary = build(items, valid_labels(args.model), second)
    write_jsonl(SFT_DIR / "train.jsonl", splits[Split.TRAIN])
    write_jsonl(SFT_DIR / "val.jsonl", splits[Split.VAL])
    write_jsonl(GOLD_CANDIDATES, splits[Split.GOLD])
    summary["teacher_model"] = args.model
    summary["agreement_model"] = args.agree_with
    (SFT_DIR / "stats.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("%s", json.dumps(summary["counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
