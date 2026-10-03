"""Measure retrieval recall@k on tests/retrieval_cases.yaml against the live corpus.

uv run python -m scripts.eval_retrieval [--k 6] [--hybrid] [--min-recall 0.8]
"""

import argparse
import asyncio
import sys

from app.config import get_settings
from app.db.client import create_client
from app.db.collections import REGULATIONS
from app.retrieval.embeddings import create_embedder
from app.retrieval.evaluation import CaseResult, evaluate, load_cases, recall


def print_report(results: list[CaseResult], k: int) -> None:
    for r in results:
        mark = "HIT " if r.hit else "MISS"
        print(f"{mark} {r.case.query[:70]:<70} expected={r.case.expected}")
        if not r.hit:
            print(f"      got: {r.retrieved}")
    print(f"\nrecall@{k} = {recall(results):.2f} ({sum(r.hit for r in results)}/{len(results)})")


async def run(k: int, hybrid: bool) -> list[CaseResult]:
    settings = get_settings()
    client = create_client(settings)
    if client is None:
        raise SystemExit("MONGODB_URI is not set")
    try:
        collection = client[settings.mongodb_db][REGULATIONS]
        return await evaluate(collection, create_embedder(settings), load_cases(), k, hybrid=hybrid)
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--hybrid", action="store_true")
    parser.add_argument("--min-recall", type=float, default=0.8)
    args = parser.parse_args(argv)
    results = asyncio.run(run(args.k, args.hybrid))
    print_report(results, args.k)
    return 0 if recall(results) >= args.min_recall else 1


if __name__ == "__main__":
    sys.exit(main())
