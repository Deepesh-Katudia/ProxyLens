"""Write data/DATASET_CARD.md from the manifest, teacher labels and SFT stats.

    uv run python -m scripts.dataset_card

Run after scripts.make_sft so the counts reflect the exported splits.
"""

import json
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from app.dataset.jsonl import read_jsonl
from app.dataset.manifest import read_manifest
from scripts.collect_notices import MANIFEST
from scripts.make_sft import SFT_DIR
from scripts.segment import ITEMS_JSONL
from scripts.teacher_label import LABELS_JSONL

logger = logging.getLogger("dataset_card")

CARD = Path("data/DATASET_CARD.md")


def _table(rows: Sequence[tuple[str, object]], headers: tuple[str, str]) -> str:
    lines = [f"| {headers[0]} | {headers[1]} |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines)


def build_card() -> str:
    stats = json.loads((SFT_DIR / "stats.json").read_text(encoding="utf-8"))
    model = stats["teacher_model"]
    entries = read_manifest(MANIFEST)
    items = list(read_jsonl(ITEMS_JSONL))
    rows = [r for r in read_jsonl(LABELS_JSONL) if r.get("label_model") == model]
    latest = {r["item_id"]: r for r in rows}  # retries append rows; the last one counts
    labels = list(latest.values())
    replied = [r for r in labels if r.get("raw_outputs")]
    retried = len(rows) - len(labels)

    meeting_types = Counter(e.meeting_type or "unknown" for e in entries)
    hosts = Counter(urlparse(e.source_url).netloc or "manual" for e in entries)
    train_types = stats["resolution_types"].get("train", {})
    cost = sum(r.get("cost_usd", 0.0) for r in rows)

    sections = [
        "# ProxyLens dataset card",
        f"_Generated {date.today().isoformat()} by `scripts/dataset_card.py`._",
        "## What it is",
        "Agenda items from Indian listed companies' general-meeting notices (AGM, EGM, postal "
        "ballot), each paired with a structured `ResolutionExtraction` (SPEC 5.1) produced by a "
        "teacher LLM. Used to fine-tune a small student model. The test set is labelled by hand "
        "and never by the teacher.",
        "## Sources",
        f"{len(entries)} notices from {len({e.company for e in entries})} companies, segmented "
        f"into {len(items)} agenda items by `app/parsing`. Notices are public regulatory "
        "filings, fetched politely (one at a time, identifying User-Agent, cached) from:",
        _table(hosts.most_common(), ("Host", "Notices")),
        _table(sorted(meeting_types.items()), ("Meeting type", "Notices")),
        "## Splits (grouped by company, no company in two splits)",
        _table(
            [
                ("train", stats["counts"]["train"]),
                ("val", stats["counts"]["val"]),
                ("gold candidates (for human labels)", stats["counts"]["gold"]),
            ],
            ("Split", "Items"),
        ),
        _table(sorted(stats["companies"].items()), ("Split", "Companies")),
        "## Teacher labels",
        f"Teacher: `{model}` via OpenRouter, temperature 0, strict JSON schema, one repair retry.",
        _table(
            [
                ("items sent to the teacher", len(labels)),
                ("calls retried after provider errors (rate limits)", retried),
                ("model replied", len(replied)),
                ("valid on first try", sum(r["valid_first_try"] for r in replied)),
                ("valid after repair", sum(r["valid"] for r in replied)),
                ("total cost (USD)", f"{cost:.2f}"),
            ],
            ("Metric", "Value"),
        ),
        "Filtering before export: " + json.dumps(stats["filtering"]),
        "### Resolution types (train)",
        _table(list(train_types.items()), ("Type", "Items")),
        "## Known biases and limits",
        "\n".join(
            [
                "- Collected via web search of the BSE filing archive and company sites, so it "
                "over-represents small and mid caps that file full notices on BSE; NSE-only "
                "filings are missing (the NSE archive blocks automated access).",
                "- English, text-based PDFs only; scanned notices and newspaper advertisements "
                "were rejected.",
                "- Notice years range mostly from FY23 to FY26, with a few older notices.",
                "- Segmentation is automatic (14/14 on hand-counted fixtures, but not "
                "perfect at this scale); a wrong split produces a malformed item.",
                "- Labels come from one teacher model and are not human-verified; errors in "
                "the teacher become errors in the student.",
                "- Company names were extracted heuristically and fixed by hand where wrong; "
                "an undetected name error could place one company in two splits.",
            ]
        ),
        "## License notes",
        "Source notices are public filings under SEBI LODR and the Companies Act. The repo "
        "stores derived text and labels, not the source PDFs (except 14 test fixtures); "
        "`data/raw/notices/manifest.csv` lists every source URL so the set can be rebuilt.",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    CARD.write_text(build_card(), encoding="utf-8")
    logger.info("Wrote %s", CARD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
