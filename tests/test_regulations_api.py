from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import regulations as regulations_api
from app.api.deps import get_db
from app.api.regulations import get_embedder
from app.config import Settings
from app.main import create_app
from app.schemas.regulation import RegulationHit, RegulationSource
from app.schemas.resolution import ResolutionType

HIT = RegulationHit(
    id="lodr_reg23_4",
    source=RegulationSource.SEBI_LODR_2015,
    citation="Regulation 23(4), SEBI LODR 2015",
    heading="Related party transactions",
    text="All material related party transactions shall require prior approval.",
    applies_to=[ResolutionType.RELATED_PARTY_TRANSACTION],
    source_url="https://example.test",
    score=0.88,
)


class FakeDb:
    def __getitem__(self, name: str) -> str:
        return name


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    recorded: list[dict[str, Any]] = []

    async def fake_retrieve(
        collection: Any, embedder: Any, q: str, rtype: Any, k: int, *, hybrid: bool
    ) -> list[RegulationHit]:
        recorded.append({"collection": collection, "q": q, "type": rtype, "k": k, "hybrid": hybrid})
        return [HIT]

    monkeypatch.setattr(regulations_api, "retrieve", fake_retrieve)
    return recorded


def _client(db: object | None) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_embedder] = lambda: object()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from _client(FakeDb())


def test_search_returns_hits_and_passes_filters(
    client: TestClient, calls: list[dict[str, Any]]
) -> None:
    resp = client.get(
        "/api/v1/regulations/search",
        params={"q": "material rpt approval", "type": "RELATED_PARTY_TRANSACTION", "k": 3},
    )

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "lodr_reg23_4"
    assert calls == [
        {
            "collection": "regulations",
            "q": "material rpt approval",
            "type": ResolutionType.RELATED_PARTY_TRANSACTION,
            "k": 3,
            "hybrid": False,
        }
    ]


@pytest.mark.parametrize(
    "params",
    [{"q": "ab"}, {"q": "valid query", "type": "NOT_A_TYPE"}, {"q": "valid query", "k": 0}],
)
def test_search_validates_input(
    client: TestClient, calls: list[dict[str, Any]], params: dict[str, Any]
) -> None:
    assert client.get("/api/v1/regulations/search", params=params).status_code == 422
    assert calls == []


def test_search_returns_503_without_database(calls: list[dict[str, Any]]) -> None:
    for client in _client(None):
        assert (
            client.get("/api/v1/regulations/search", params={"q": "valid query"}).status_code == 503
        )
