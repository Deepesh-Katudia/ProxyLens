"""Regulation retrieval: Atlas `$vectorSearch`, optionally fused with `$search` (RRF)."""

from collections.abc import Sequence
from typing import Any

from pymongo.asynchronous.collection import AsyncCollection
from starlette.concurrency import run_in_threadpool

from app.db.client import Document
from app.db.collections import REGULATIONS_TEXT_INDEX, REGULATIONS_VECTOR_INDEX
from app.retrieval.embeddings import Embedder
from app.schemas.regulation import RegulationHit
from app.schemas.resolution import ResolutionType

DEFAULT_K = 6
CANDIDATES_PER_RESULT = 20  # numCandidates = k * this; Atlas recommends 10-20x
RRF_K = 60  # standard reciprocal-rank-fusion damping constant
HYBRID_POOL = 20  # results pulled from each retriever before fusion

_PROJECTION = {
    "_id": 0,
    "id": "$_id",
    "source": 1,
    "citation": 1,
    "heading": 1,
    "text": 1,
    "applies_to": 1,
    "source_url": 1,
    "notes": 1,
}


def vector_pipeline(
    query_vector: Sequence[float],
    k: int,
    resolution_type: ResolutionType | None = None,
) -> list[dict[str, Any]]:
    stage: dict[str, Any] = {
        "index": REGULATIONS_VECTOR_INDEX,
        "path": "embedding",
        "queryVector": list(query_vector),
        "numCandidates": k * CANDIDATES_PER_RESULT,
        "limit": k,
    }
    if resolution_type is not None:
        stage["filter"] = {"applies_to": {"$in": [resolution_type.value]}}
    return [
        {"$vectorSearch": stage},
        {"$project": {**_PROJECTION, "score": {"$meta": "vectorSearchScore"}}},
    ]


def text_pipeline(
    query: str,
    k: int,
    resolution_type: ResolutionType | None = None,
) -> list[dict[str, Any]]:
    compound: dict[str, Any] = {
        "must": [{"text": {"query": query, "path": ["text", "heading", "citation"]}}]
    }
    if resolution_type is not None:
        compound["filter"] = [{"in": {"path": "applies_to", "value": [resolution_type.value]}}]
    return [
        {"$search": {"index": REGULATIONS_TEXT_INDEX, "compound": compound}},
        {"$limit": k},
        {"$project": {**_PROJECTION, "score": {"$meta": "searchScore"}}},
    ]


def rrf_fuse(rankings: Sequence[Sequence[str]], rrf_k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal-rank fusion: score(d) = sum over rankings of 1 / (rrf_k + rank)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


async def _run(
    collection: AsyncCollection[Document], pipeline: list[dict[str, Any]]
) -> list[Document]:
    cursor = await collection.aggregate(pipeline)
    return [doc async for doc in cursor]


async def retrieve(
    collection: AsyncCollection[Document],
    embedder: Embedder,
    query: str,
    resolution_type: ResolutionType | None = None,
    k: int = DEFAULT_K,
    *,
    hybrid: bool = False,
) -> list[RegulationHit]:
    """Top-k regulation chunks for a query, optionally restricted to a resolution type."""
    query_vector = await run_in_threadpool(embedder.embed_query, query)
    if not hybrid:
        docs = await _run(collection, vector_pipeline(query_vector, k, resolution_type))
        return [RegulationHit.model_validate(d) for d in docs]

    vector_docs = await _run(
        collection, vector_pipeline(query_vector, HYBRID_POOL, resolution_type)
    )
    text_docs = await _run(collection, text_pipeline(query, HYBRID_POOL, resolution_type))
    by_id = {d["id"]: d for d in [*text_docs, *vector_docs]}
    fused = rrf_fuse([[d["id"] for d in vector_docs], [d["id"] for d in text_docs]])
    return [
        RegulationHit.model_validate({**by_id[doc_id], "score": score})
        for doc_id, score in fused[:k]
    ]
