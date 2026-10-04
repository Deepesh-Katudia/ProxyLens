"""Upload -> background job -> report -> feedback, through the HTTP API (SPEC 9).

Uses the in-memory store and the mocked models from test_pipeline; TestClient runs
background tasks before returning, so a job is finished when the upload returns."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.api.documents import get_runner, get_store
from app.config import Settings, get_settings
from app.main import create_app
from app.pipeline.nodes import PipelineDeps, Progress
from app.reports.models import JobStatus
from app.reports.runner import JobRunner
from app.reports.store import InMemoryReportStore
from tests.test_pipeline import NOTICE, NOTICE_ITEMS, deps

KEY = "test-key"
HEADERS = {"X-API-Key": KEY}


class RecordingStore(InMemoryReportStore):
    def __init__(self) -> None:
        super().__init__()
        self.statuses: list[str] = []

    async def update_job(self, job_id: str, **fields: Any) -> None:
        if "status" in fields:
            self.statuses.append(JobStatus(fields["status"]).value)
        await super().update_job(job_id, **fields)


@pytest.fixture
def store() -> RecordingStore:
    return RecordingStore()


def make_client(store: RecordingStore, **settings: Any) -> Iterator[TestClient]:
    app_settings = Settings(_env_file=None, api_key=KEY, **settings)
    app = create_app(app_settings)
    app.dependency_overrides[get_settings] = lambda: app_settings

    def factory(progress: Progress) -> PipelineDeps:
        base = deps()
        return PipelineDeps(**{**base.__dict__, "progress": progress})

    runner = JobRunner(store, factory)
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_runner] = lambda: runner
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(store: RecordingStore) -> Iterator[TestClient]:
    yield from make_client(store)


def upload(client: TestClient, pdf: bytes, **form: Any) -> Any:
    return client.post(
        "/api/v1/documents",
        files={"file": ("notice.pdf", pdf, "application/pdf")},
        data=form,
        headers=HEADERS,
    )


def text_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    data: bytes = doc.tobytes()
    return data


def test_upload_analyse_and_read_the_report(client: TestClient, store: RecordingStore) -> None:
    response = upload(client, NOTICE.read_bytes(), turnover_cr="70000")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["duplicate"] is False
    job = client.get(f"/api/v1/jobs/{body['job_id']}").json()
    assert job["status"] == "done" and job["done"] == job["total"] == NOTICE_ITEMS
    assert store.statuses[0] == "parsing" and store.statuses[-1] == "done"
    assert {"extracting", "analysing"} <= set(store.statuses)

    report = client.get(f"/api/v1/documents/{body['document_id']}").json()
    assert report["document"]["company"] == "ITC Limited"
    assert report["document"]["meeting_type"] == "AGM"
    assert report["document"]["item_count"] == NOTICE_ITEMS
    assert report["document"]["company_facts"]["turnover_inr"] == 70000 * 10_000_000
    assert [i["resolution"]["seq"] for i in report["items"]] == list(range(1, NOTICE_ITEMS + 1))
    first = report["items"][0]
    assert first["analysis"]["recommendation"] == "FOR"
    assert first["resolution"]["raw_text"]

    one = client.get(f"/api/v1/resolutions/{first['resolution']['id']}").json()
    assert one["analysis"]["id"] == first["analysis"]["id"]
    listed = client.get("/api/v1/documents").json()
    assert [d["id"] for d in listed] == [body["document_id"]]


def test_feedback_is_saved_and_shown_on_the_report(client: TestClient) -> None:
    body = upload(client, NOTICE.read_bytes()).json()
    report = client.get(f"/api/v1/documents/{body['document_id']}").json()
    analysis_id = report["items"][2]["analysis"]["id"]
    override = {"analyst_recommendation": "AGAINST", "reason": "Tenure breaches s.149(11)."}

    saved = client.post(f"/api/v1/analyses/{analysis_id}/feedback", json=override, headers=HEADERS)

    assert saved.status_code == 201, saved.text
    assert saved.json()["analysis_id"] == analysis_id
    again = client.get(f"/api/v1/documents/{body['document_id']}").json()
    assert again["items"][2]["feedback"][0]["reason"] == "Tenure breaches s.149(11)."
    assert again["items"][0]["feedback"] == []


def test_feedback_validation_and_auth(client: TestClient) -> None:
    override = {"analyst_recommendation": "AGAINST", "reason": "why"}

    assert (
        client.post("/api/v1/analyses/nope/feedback", json=override, headers=HEADERS).status_code
        == 404
    )
    assert client.post("/api/v1/analyses/x/feedback", json=override).status_code == 401
    bad = {"analyst_recommendation": "MAYBE", "reason": "why"}
    assert client.post("/api/v1/analyses/x/feedback", json=bad, headers=HEADERS).status_code == 422


def test_same_pdf_twice_reuses_the_analysis(client: TestClient, store: RecordingStore) -> None:
    first = upload(client, NOTICE.read_bytes()).json()

    second = upload(client, NOTICE.read_bytes()).json()
    different_inputs = upload(client, NOTICE.read_bytes(), net_profit_cr="5000").json()

    assert second == {**first, "duplicate": True}
    assert different_inputs["duplicate"] is False
    assert len(store.documents) == 2


def test_upload_rejects_non_pdfs_and_missing_key(client: TestClient) -> None:
    not_pdf = client.post(
        "/api/v1/documents", files={"file": ("x.pdf", b"hello", "application/pdf")}, headers=HEADERS
    )
    no_key = client.post(
        "/api/v1/documents", files={"file": ("x.pdf", b"%PDF-1.7", "application/pdf")}
    )

    assert not_pdf.status_code == 415
    assert no_key.status_code == 401


def test_upload_size_limit(store: RecordingStore) -> None:
    client = next(make_client(store, max_upload_mb=1))

    response = upload(client, b"%PDF-" + b"0" * 1_100_000)

    assert response.status_code == 413


def test_a_pdf_without_agenda_items_fails_the_job(client: TestClient) -> None:
    body = upload(client, text_pdf("Quarterly newsletter. Nothing to vote on.")).json()

    job = client.get(f"/api/v1/jobs/{body['job_id']}").json()

    assert job["status"] == "failed"
    assert job["error"].startswith("no 'notice is hereby given' found")
    assert client.get(f"/api/v1/documents/{body['document_id']}").json()["items"] == []


def test_unknown_ids_are_404(client: TestClient) -> None:
    for path in ("documents/abc", "jobs/abc", "resolutions/abc", "eval/latest"):
        assert client.get(f"/api/v1/{path}").status_code == 404, path


def test_eval_latest_returns_the_newest_run(client: TestClient, store: RecordingStore) -> None:
    store.eval_runs.append({"run_id": "r1", "metrics": {"json_valid": 0.9}})

    assert client.get("/api/v1/eval/latest").json()["run_id"] == "r1"


def test_fixture_notice_exists() -> None:
    assert Path(NOTICE).is_file()
