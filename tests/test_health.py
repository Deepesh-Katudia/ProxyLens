from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.api.deps import get_db
from app.config import Settings
from app.main import create_app


class FakeDb:
    """Minimal stand-in for an AsyncDatabase that only answers `ping`."""

    def __init__(self, *, reachable: bool) -> None:
        self.reachable = reachable

    async def command(self, name: str) -> dict[str, Any]:
        if not self.reachable:
            raise ServerSelectionTimeoutError("no servers")
        assert name == "ping"
        return {"ok": 1.0}


def make_client(db: FakeDb | None) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client


@pytest.fixture
def healthy_client() -> Iterator[TestClient]:
    yield from make_client(FakeDb(reachable=True))


@pytest.fixture
def down_client() -> Iterator[TestClient]:
    yield from make_client(FakeDb(reachable=False))


@pytest.fixture
def unconfigured_client() -> Iterator[TestClient]:
    yield from make_client(None)


@pytest.mark.parametrize("path", ["/healthz", "/api/v1/healthz"])
def test_healthz_returns_200_when_db_reachable(healthy_client: TestClient, path: str) -> None:
    resp = healthy_client.get(path)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok", "model": "not_loaded"}


def test_healthz_returns_503_when_db_unreachable(down_client: TestClient) -> None:
    resp = down_client.get("/healthz")

    assert resp.status_code == 503
    assert resp.json()["db"] == "unreachable"


def test_healthz_returns_503_when_db_not_configured(unconfigured_client: TestClient) -> None:
    resp = unconfigured_client.get("/healthz")

    assert resp.status_code == 503
    assert resp.json()["db"] == "not_configured"


def test_lifespan_leaves_db_unset_without_uri() -> None:
    app = create_app(Settings(_env_file=None))

    with TestClient(app):
        assert app.state.db is None
