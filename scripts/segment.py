"""Split every notice in the manifest into items (SPEC 7.2 step 2).

    uv run python -m scripts.segment

Writes data/processed/items.jsonl, one row per agenda item, keyed by
`item_id` = "<doc_id>-<seq>".
"""

import logging
import sys
from pathlib import Path
from typing import Any

from app.dataset.jsonl import write_jsonl
from app.dataset.manifest import NoticeEntry, read_manifest
from app.parsing.notice import parse_notice_pdf
from scripts.collect_notices import MANIFEST, NOTICES_DIR

logger = logging.getLogger("segment")

ITEMS_JSONL = Path("data/processed/items.jsonl")


def item_rows(entry: NoticeEntry) -> list[dict[str, Any]]:
    notice = parse_notice_pdf(NOTICES_DIR / entry.file)
    meeting_type = entry.meeting_type or notice.meeting_type.value
    return [
        {
            "item_id": f"{entry.doc_id}-{item.seq}",
            "doc_id": entry.doc_id,
            "file": entry.file,
            "company": entry.company,
            "meeting_type": meeting_type,
            "seq": item.seq,
            "item_no": item.item_no,
            "section": item.section.value if item.section else None,
            "resolution_kind_hint": (
                item.resolution_kind_hint.value if item.resolution_kind_hint else None
            ),
            "text": item.text,
            "explanatory_statement": item.explanatory_statement,
        }
        for item in notice.items
    ]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rows: list[dict[str, Any]] = []
    failed: list[str] = []
    for entry in read_manifest(MANIFEST):
        if not (NOTICES_DIR / entry.file).exists():
            continue
        try:
            items = item_rows(entry)
        except Exception as exc:  # report and continue; one odd PDF shouldn't stop the run
            logger.error("%s: %s", entry.file, exc)
            failed.append(entry.file)
            continue
        if not items:
            logger.warning("%s: no items found", entry.file)
            failed.append(entry.file)
        rows += items
    count = write_jsonl(ITEMS_JSONL, rows)
    logger.info("Wrote %d items to %s; %d notices failed", count, ITEMS_JSONL, len(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
