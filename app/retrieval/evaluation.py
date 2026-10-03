"""Retrieval evaluation: recall@k over hand-written query cases."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pymongo.asynchronous.collection import AsyncCollection

from app.db.client import Document
from app.retrieval.embeddings import Embedder
from app.retrieval.search import retrieve
from app.schemas.resolution import ResolutionType

DEFAULT_CASES_PATH = Path("tests/retrieval_cases.yaml")


class RetrievalCase(BaseModel):
    query: str
    resolution_type: ResolutionType | None = None
    # Any of these legal units in the top k counts as a hit.
    expected: list[str] = Field(min_length=1)


@dataclass(frozen=True)
class CaseResult:
    case: RetrievalCase
    retrieved: list[str]
    hit: bool


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[RetrievalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [RetrievalCase.model_validate(item) for item in raw["cases"]]


def matches(chunk_id: str, unit_id: str) -> bool:
    """True if a chunk belongs to a unit; long units are split into `<unit>_p<n>`."""
    return chunk_id == unit_id or chunk_id.startswith(f"{unit_id}_p")


def is_hit(retrieved: Sequence[str], expected: Sequence[str]) -> bool:
    return any(matches(r, e) for r in retrieved for e in expected)


def recall(results: Sequence[CaseResult]) -> float:
    return sum(r.hit for r in results) / len(results) if results else 0.0


async def evaluate(
    collection: AsyncCollection[Document],
    embedder: Embedder,
    cases: Sequence[RetrievalCase],
    k: int,
    *,
    hybrid: bool = False,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        hits = await retrieve(
            collection, embedder, case.query, case.resolution_type, k, hybrid=hybrid
        )
        ids = [h.id for h in hits]
        results.append(CaseResult(case, ids, is_hit(ids, case.expected)))
    return results
