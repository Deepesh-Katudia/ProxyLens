from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from app.corpus.sources import amended_up_to
from app.retrieval.evaluation import CaseResult, RetrievalCase, is_hit, load_cases, matches, recall
from app.retrieval.search import retrieve, rrf_fuse, text_pipeline, vector_pipeline
from app.schemas.resolution import ResolutionType as T


class FakeEmbedder:
    dim = 3

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


def _doc(doc_id: str, score: float) -> dict[str, Any]:
    return {
        "id": doc_id,
        "source": "SEBI_LODR_2015",
        "citation": f"Regulation {doc_id}",
        "heading": "",
        "text": "text",
        "applies_to": ["RELATED_PARTY_TRANSACTION"],
        "source_url": "https://example.test",
        "score": score,
    }


class FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = iter(docs)

    def __aiter__(self) -> "FakeCursor":
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._docs)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeCollection:
    """Answers $vectorSearch and $search pipelines with canned results."""

    def __init__(self, vector: list[dict[str, Any]], text: list[dict[str, Any]]) -> None:
        self.vector, self.text = vector, text
        self.pipelines: list[list[dict[str, Any]]] = []

    async def aggregate(self, pipeline: list[dict[str, Any]]) -> FakeCursor:
        self.pipelines.append(pipeline)
        return FakeCursor(self.vector if "$vectorSearch" in pipeline[0] else self.text)


def test_vector_pipeline_filters_by_resolution_type() -> None:
    stage = vector_pipeline([0.1], 6, T.RELATED_PARTY_TRANSACTION)[0]["$vectorSearch"]

    assert stage["filter"] == {"applies_to": {"$in": ["RELATED_PARTY_TRANSACTION"]}}
    assert stage["limit"] == 6
    assert stage["numCandidates"] >= 60


def test_vector_pipeline_without_type_has_no_filter() -> None:
    assert "filter" not in vector_pipeline([0.1], 6)[0]["$vectorSearch"]


def test_text_pipeline_filters_with_in_operator() -> None:
    compound = text_pipeline("rpt", 5, T.DIVIDEND)[0]["$search"]["compound"]

    assert compound["filter"] == [{"in": {"path": "applies_to", "value": ["DIVIDEND"]}}]


def test_rrf_rewards_documents_ranked_by_both_retrievers() -> None:
    fused = rrf_fuse([["a", "b", "c"], ["c", "a"]])

    assert [doc_id for doc_id, _ in fused] == ["a", "c", "b"]


async def test_retrieve_vector_only_returns_hits_in_order() -> None:
    collection = FakeCollection([_doc("x", 0.9), _doc("y", 0.8)], [])

    hits = await retrieve(collection, FakeEmbedder(), "query", T.RELATED_PARTY_TRANSACTION, k=2)  # type: ignore[arg-type]

    assert [h.id for h in hits] == ["x", "y"]
    assert len(collection.pipelines) == 1


async def test_retrieve_hybrid_fuses_both_rankings() -> None:
    collection = FakeCollection(
        vector=[_doc("x", 0.9), _doc("y", 0.8)],
        text=[_doc("y", 12.0), _doc("z", 9.0)],
    )

    hits = await retrieve(collection, FakeEmbedder(), "query", k=3, hybrid=True)  # type: ignore[arg-type]

    assert hits[0].id == "y"
    assert {h.id for h in hits} == {"x", "y", "z"}


@pytest.mark.parametrize(
    ("chunk_id", "unit_id", "expected"),
    [
        ("lodr_reg23_4", "lodr_reg23_4", True),
        ("lodr_reg23_4_p2", "lodr_reg23_4", True),
        ("lodr_reg23_1a", "lodr_reg23_1", False),
        ("lodr_reg23_1", "lodr_reg23_1a", False),
    ],
)
def test_matches_respects_unit_boundaries(chunk_id: str, unit_id: str, expected: bool) -> None:
    assert matches(chunk_id, unit_id) is expected


def test_recall_counts_hits() -> None:
    case = RetrievalCase(query="q", expected=["a"])
    results = [CaseResult(case, ["a"], True), CaseResult(case, ["b"], False)]

    assert recall(results) == 0.5
    assert recall([]) == 0.0
    assert is_hit(["b", "a_p1"], ["a"])


def test_repo_retrieval_cases_are_valid() -> None:
    cases = load_cases(Path("tests/retrieval_cases.yaml"))

    assert len(cases) >= 20
    assert all(case.expected for case in cases)


def test_amended_up_to_parses_banner() -> None:
    assert amended_up_to("REGULATIONS, 2015\n [Amended up to July 14, 2026]") == "2026-07-14"
    assert amended_up_to("no banner here") is None
