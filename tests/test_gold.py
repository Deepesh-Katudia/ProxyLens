from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.gold import get_gold_store
from app.config import Settings, get_settings
from app.dataset.jsonl import write_jsonl
from app.gold.store import GoldLabel, GoldStore, LabelStatus
from app.main import create_app

EXTRACTION = {
    "item_no": 2,
    "title": "Re-appoint Mr. A as Independent Director",
    "resolution_type": "INDEPENDENT_DIRECTOR_APPOINT",
    "is_special_resolution": True,
}


@pytest.fixture
def store(tmp_path: Path) -> GoldStore:
    candidates = tmp_path / "candidates.jsonl"
    write_jsonl(
        candidates,
        [
            {
                "item_id": "g-1",
                "company": "Gold Co Ltd",
                "item_no": 1,
                "text": "To adopt accounts.",
            },
            {
                "item_id": "g-2",
                "company": "Gold Co Ltd",
                "item_no": 2,
                "text": "To re-appoint Mr. A.",
            },
        ],
    )
    return GoldStore(candidates, tmp_path / "labels.jsonl")


def test_latest_label_wins_and_history_is_kept(store: GoldStore) -> None:
    store.save_label("g-2", GoldLabel(status=LabelStatus.SKIPPED, skip_reason="unclear"))
    store.save_label("g-2", GoldLabel(status=LabelStatus.LABELLED, extraction=EXTRACTION))

    item = store.get_item("g-2")

    assert item is not None and item.label is not None
    assert item.label.status is LabelStatus.LABELLED
    assert len(store.labels_path.read_text(encoding="utf-8").splitlines()) == 2


def test_unknown_items_are_rejected(store: GoldStore) -> None:
    assert store.get_item("nope") is None
    with pytest.raises(KeyError):
        store.save_label("nope", GoldLabel(status=LabelStatus.SKIPPED, skip_reason="x"))


@pytest.mark.parametrize(
    "payload",
    [{"status": "labelled"}, {"status": "skipped"}],
)
def test_label_requires_extraction_or_reason(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        GoldLabel.model_validate(payload)


@pytest.fixture
def client(store: GoldStore) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_gold_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, api_key="k3y")
    with TestClient(app) as test_client:
        yield test_client


def test_list_reports_progress(client: TestClient, store: GoldStore) -> None:
    store.save_label("g-1", GoldLabel(status=LabelStatus.SKIPPED, skip_reason="notes, not an item"))

    body = client.get("/api/v1/gold/items").json()

    assert (body["total"], body["labelled"], body["skipped"]) == (2, 0, 1)
    assert body["items"][0]["status"] == "skipped"


def test_save_label_needs_the_api_key(client: TestClient) -> None:
    payload = {"status": "labelled", "extraction": EXTRACTION}

    assert client.put("/api/v1/gold/items/g-2/label", json=payload).status_code == 401
    ok = client.put("/api/v1/gold/items/g-2/label", json=payload, headers={"X-API-Key": "k3y"})
    assert ok.status_code == 204
    assert client.get("/api/v1/gold/items/g-2").json()["label"]["status"] == "labelled"


def test_save_label_validates_payload(client: TestClient) -> None:
    bad = {"status": "labelled", "extraction": {**EXTRACTION, "resolution_type": "NOPE"}}

    resp = client.put("/api/v1/gold/items/g-2/label", json=bad, headers={"X-API-Key": "k3y"})

    assert resp.status_code == 422


def test_writes_fail_closed_without_configured_key(store: GoldStore) -> None:
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_gold_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    with TestClient(app) as test_client:
        resp = test_client.put(
            "/api/v1/gold/items/g-1/label",
            json={"status": "skipped", "skip_reason": "x"},
            headers={"X-API-Key": ""},
        )
    assert resp.status_code == 503
