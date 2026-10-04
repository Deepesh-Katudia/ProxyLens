"""Run one notice PDF through the full pipeline against the live services.

    uv run python -m scripts.analyse_notice NOTICE.pdf [--extractor teacher|student]
        [--out analysis.json] [--turnover-cr N] [--net-profit-cr N]

Extraction uses the fine-tuned student (with teacher fallback) by default;
`--extractor teacher` skips the slow local model. The reasoner is the teacher.
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.config import get_settings
from app.db.client import create_client
from app.db.collections import REGULATIONS
from app.llm.providers import create_student, create_teacher
from app.pipeline.graph import analyse_notice, atlas_retriever
from app.pipeline.nodes import PipelineDeps
from app.retrieval.embeddings import create_embedder
from app.rules.engine import load_policy
from app.rules.models import CompanyFacts
from app.schemas.analysis import ItemAnalysis

CRORE = 10_000_000


def print_report(analyses: list[ItemAnalysis]) -> None:
    for a in analyses:
        kind = a.resolution_type.value if a.resolution_type else "?"
        print(f"\n#{a.item_no} {a.title[:70]}  [{kind}]")
        print(f"   {a.recommendation.value}  confidence {a.confidence:.2f}  flags {a.flags or '-'}")
        for f in a.rule_findings:
            print(f"   {f.kind.value:6} {f.rule_id:28} {f.status.value:17} {f.detail[:90]}")
        print(f"   rationale: {a.rationale}")
        for c in a.citations:
            print(f'   cites [{c.regulation_id}] "{c.quote[:90]}"')
        for adj in a.adjustments:
            print(f"   adjusted: {adj}")


async def run(pdf: bytes, extractor: str, company: CompanyFacts) -> list[ItemAnalysis]:
    settings = get_settings()
    client = create_client(settings)
    if client is None:
        raise SystemExit("MONGODB_URI is not set")
    teacher = create_teacher(settings)
    try:
        deps = PipelineDeps(
            student=teacher if extractor == "teacher" else create_student(settings),
            teacher=None if extractor == "teacher" else teacher,
            reasoner=teacher,
            retriever=atlas_retriever(
                client[settings.mongodb_db][REGULATIONS], create_embedder(settings)
            ),
            rules=load_policy(),
        )
        return await analyse_notice(deps, pdf, company)
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--extractor", choices=["student", "teacher"], default="student")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--turnover-cr", type=float)
    parser.add_argument("--net-profit-cr", type=float)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # rationales contain the rupee sign
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    company = CompanyFacts(
        turnover_inr=args.turnover_cr * CRORE if args.turnover_cr is not None else None,
        net_profit_inr=args.net_profit_cr * CRORE if args.net_profit_cr is not None else None,
    )
    analyses = asyncio.run(run(args.pdf.read_bytes(), args.extractor, company))
    print_report(analyses)
    if args.out:
        payload = [a.model_dump(mode="json") for a in analyses]
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
