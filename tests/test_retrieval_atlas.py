"""Phase 1 acceptance: recall@6 >= 0.8 against the live Atlas corpus.

Opt-in because it needs MONGODB_URI, a built corpus and the embedding model:
    RUN_ATLAS_TESTS=1 uv run pytest tests/test_retrieval_atlas.py
"""

import os

import pytest

from app.config import get_settings
from app.db.client import create_client
from app.db.collections import REGULATIONS
from app.retrieval.embeddings import create_embedder
from app.retrieval.evaluation import evaluate, load_cases, recall

MIN_RECALL_AT_6 = 0.8

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_ATLAS_TESTS") != "1", reason="set RUN_ATLAS_TESTS=1 to run against Atlas"
)


async def test_recall_at_6_meets_phase_1_target() -> None:
    settings = get_settings()
    client = create_client(settings)
    assert client is not None, "MONGODB_URI must be set"
    try:
        results = await evaluate(
            client[settings.mongodb_db][REGULATIONS], create_embedder(settings), load_cases(), k=6
        )
    finally:
        await client.close()

    misses = [r.case.query for r in results if not r.hit]
    assert recall(results) >= MIN_RECALL_AT_6, f"misses: {misses}"
