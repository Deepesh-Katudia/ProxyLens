"""Phase 4 acceptance: load the student GGUF and extract 10 val items.

    uv run python -m scripts.smoke_student                  # model from .env (HF Hub or path)
    uv run python -m scripts.smoke_student --gguf model.gguf --n 10 --unconstrained

Reports JSON validity (first try, as SPEC 8 defines it), resolution-type
agreement with the teacher label, and latency per item.
"""

import argparse
import json
import logging
import statistics
import sys
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.dataset.jsonl import read_jsonl
from app.llm.extraction import extract
from app.llm.local_gguf import LocalGGUFProvider, resolve_gguf_path
from scripts.make_sft import SFT_DIR

logger = logging.getLogger("smoke_student")

USER_PREFIX = "AGENDA ITEM No. "


def parse_user_message(content: str) -> tuple[int, str, str | None]:
    """Invert build_extraction_input: (item_no, item text, statement or None)."""
    head, _, rest = content.partition(":\n")
    item_no = int(head.removeprefix(USER_PREFIX))
    text, _, statement = rest.partition("\n\nEXPLANATORY STATEMENT:\n")
    return item_no, text, None if statement == "(none)" else statement


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gguf", type=Path, help="local .gguf (default: from .env)")
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--unconstrained", action="store_true", help="no grammar constraint")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = get_settings()
    path = args.gguf or resolve_gguf_path(settings)
    student = LocalGGUFProvider(
        path, n_threads=settings.student_n_threads, constrained=not args.unconstrained
    )
    results: list[dict[str, Any]] = []
    for row in list(read_jsonl(SFT_DIR / "val.jsonl"))[: args.n]:
        item_no, text, statement = parse_user_message(row["messages"][1]["content"])
        teacher_type = json.loads(row["messages"][2]["content"])["resolution_type"]
        outcome = extract(student, item_no, text, statement)
        got = outcome.extraction.resolution_type.value if outcome.extraction else None
        results.append(
            {
                "valid_first_try": outcome.valid_first_try,
                "valid": outcome.valid,
                "type_match": got == teacher_type,
                "latency_s": outcome.latency_ms / 1000,
            }
        )
        logger.info("item %s: valid=%s type=%s (teacher %s) %.1fs", item_no, outcome.valid,
                    got, teacher_type, outcome.latency_ms / 1000)  # fmt: skip

    n = len(results)
    print(
        f"\n{n} items | valid first try {sum(r['valid_first_try'] for r in results)}/{n} | "
        f"valid after repair {sum(r['valid'] for r in results)}/{n} | "
        f"type matches teacher {sum(r['type_match'] for r in results)}/{n} | "
        f"median latency {statistics.median(r['latency_s'] for r in results):.1f}s"
    )
    return 0 if all(r["valid"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
