"""Structured logging, request IDs and per-node latency (SPEC Phase 8)."""

import json
import logging
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app, preload
from app.observability import (
    REQUEST_ID_HEADER,
    JsonFormatter,
    bind_request_id,
    clean_request_id,
    configure_logging,
    current_request_id,
    timed_node,
)
from app.pipeline.graph import NODE_ORDER, build_graph
from app.pipeline.state import PipelineState
from tests.test_documents_api import RecordingStore, make_client, upload
from tests.test_pipeline import NOTICE, deps

NODE_LOGGER = "app.pipeline.graph"


def record(msg: str, level: int = logging.INFO, **extra: object) -> logging.LogRecord:
    rec = logging.LogRecord("app.test", level, __file__, 1, msg, None, None)
    rec.__dict__.update(extra)
    return rec


def node_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == NODE_LOGGER and hasattr(r, "node")]


def test_json_formatter_emits_cloud_logging_fields_and_extras() -> None:
    with bind_request_id("req-1"):
        line = JsonFormatter().format(record("node done", node="parse", duration_ms=12))

    payload = json.loads(line)
    assert payload["severity"] == "INFO"
    assert payload["message"] == "node done"
    assert payload["logger"] == "app.test"
    assert payload["request_id"] == "req-1"
    assert payload["node"] == "parse" and payload["duration_ms"] == 12
    assert "time" in payload


def test_json_formatter_includes_the_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )

    payload = json.loads(JsonFormatter().format(rec))
    assert payload["severity"] == "ERROR"
    assert "ValueError: boom" in payload["exception"]


def test_json_formatter_survives_unserialisable_extras() -> None:
    payload = json.loads(JsonFormatter().format(record("x", path=Path("a/b"))))

    assert payload["path"] == str(Path("a/b"))


@pytest.mark.parametrize("value", ["req-123", "abc.DEF_9", "a" * 64])
def test_clean_request_id_keeps_safe_ids(value: str) -> None:
    assert clean_request_id(value) == value


@pytest.mark.parametrize("value", [None, "", "has space", "new\nline", "a" * 65, '"quoted"'])
def test_clean_request_id_replaces_unsafe_ids(value: str | None) -> None:
    cleaned = clean_request_id(value)

    assert cleaned != value
    assert len(cleaned) == 32 and cleaned.isalnum()


def test_bind_request_id_restores_the_previous_value() -> None:
    assert current_request_id() is None
    with bind_request_id("outer"):
        with bind_request_id("inner"):
            assert current_request_id() == "inner"
        assert current_request_id() == "outer"
    assert current_request_id() is None


def test_configure_logging_installs_one_json_handler() -> None:
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    try:
        configure_logging("WARNING", "json")
        configure_logging("INFO", "json")  # idempotent: no duplicate handlers

        ours = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
        assert len(ours) == 1
        assert root.level == logging.INFO
    finally:
        root.handlers[:], _ = saved
        root.setLevel(saved[1])


async def test_timed_node_logs_latency_for_sync_and_async_nodes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def sync_node(state: PipelineState) -> dict[str, int]:
        return {"sync": 1}

    async def async_node(state: PipelineState) -> dict[str, int]:
        return {"async": 2}

    caplog.set_level(logging.INFO, logger=NODE_LOGGER)
    with bind_request_id("req-9"):
        assert timed_node("a", sync_node)(PipelineState()) == {"sync": 1}
        assert await timed_node("b", async_node)(PipelineState()) == {"async": 2}

    logged = node_records(caplog)
    assert [r.node for r in logged] == ["a", "b"]  # type: ignore[attr-defined]
    assert all(r.request_id == "req-9" for r in logged)  # type: ignore[attr-defined]
    assert all(isinstance(r.duration_ms, int) and r.duration_ms >= 0 for r in logged)  # type: ignore[attr-defined]


async def test_timed_node_logs_failures_and_reraises(caplog: pytest.LogCaptureFixture) -> None:
    def broken(state: PipelineState) -> dict[str, int]:
        raise RuntimeError("bad node")

    caplog.set_level(logging.INFO, logger=NODE_LOGGER)
    with pytest.raises(RuntimeError, match="bad node"):
        timed_node("broken", broken)(PipelineState())

    (rec,) = node_records(caplog)
    assert rec.levelno == logging.ERROR and rec.node == "broken"  # type: ignore[attr-defined]


async def test_every_pipeline_node_logs_its_latency(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=NODE_LOGGER)
    with bind_request_id("req-graph"):
        await build_graph(deps()).ainvoke(PipelineState(pdf=NOTICE.read_bytes()))

    logged = node_records(caplog)
    assert [r.node for r in logged] == list(NODE_ORDER)  # type: ignore[attr-defined]
    assert {r.request_id for r in logged} == {"req-graph"}  # type: ignore[attr-defined]


@pytest.fixture
def plain_client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(_env_file=None))) as client:
        yield client


def test_responses_carry_a_generated_request_id(plain_client: TestClient) -> None:
    resp = plain_client.get("/api/v1/regulations/search", params={"q": "x"})

    rid = resp.headers[REQUEST_ID_HEADER]
    assert len(rid) == 32 and rid.isalnum()


def test_a_safe_incoming_request_id_is_echoed(plain_client: TestClient) -> None:
    resp = plain_client.get("/healthz", headers={REQUEST_ID_HEADER: "client-42"})

    assert resp.headers[REQUEST_ID_HEADER] == "client-42"


def test_an_unsafe_incoming_request_id_is_replaced(plain_client: TestClient) -> None:
    resp = plain_client.get("/healthz", headers={REQUEST_ID_HEADER: "x" * 200})

    assert resp.headers[REQUEST_ID_HEADER] != "x" * 200


def test_the_upload_request_id_reaches_every_pipeline_node(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=NODE_LOGGER)
    store = RecordingStore()
    for client in make_client(store):
        client.headers[REQUEST_ID_HEADER] = "upload-7"
        resp = upload(client, NOTICE.read_bytes())
        assert resp.status_code == 202

    logged = node_records(caplog)
    assert logged, "the background job logged no node timings"
    assert {r.request_id for r in logged} == {"upload-7"}  # type: ignore[attr-defined]


class FakeEmbedder:
    dim = 3

    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.0] * 3


class FakeFactory:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.warmed = 0

    def warm_up(self) -> None:
        if self.fail:
            raise RuntimeError("HF Hub unreachable")
        self.warmed += 1


def test_preload_warms_the_embedder_and_the_student() -> None:
    embedder, factory = FakeEmbedder(), FakeFactory()

    preload(embedder, factory)

    assert len(embedder.queries) == 1 and factory.warmed == 1


def test_preload_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    embedder = FakeEmbedder()

    preload(embedder, FakeFactory(fail=True))

    assert embedder.queries  # the embedder still warmed
    assert "preload failed" in caplog.text


@pytest.mark.parametrize("enabled", [True, False])
def test_startup_preloads_only_when_enabled(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    called = threading.Event()
    monkeypatch.setattr("app.main.preload", lambda embedder, factory: called.set())

    with TestClient(create_app(Settings(_env_file=None, preload_models=enabled))) as client:
        client.get("/healthz")
        assert called.wait(timeout=5 if enabled else 0.2) is enabled


def test_access_log_is_written_before_background_tasks_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from fastapi import BackgroundTasks, FastAPI

    from app.observability import RequestIdMiddleware

    seen_by_task: list[int] = []
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    def slow_job() -> None:
        seen_by_task.append(sum(r.name == "app.http" for r in caplog.records))

    @app.post("/start")
    async def start(background: BackgroundTasks) -> dict[str, bool]:
        background.add_task(slow_job)
        return {"ok": True}

    caplog.set_level(logging.INFO, logger="app.http")
    with TestClient(app) as client:
        client.post("/start")

    assert seen_by_task == [1]  # the request was logged before the job started
    assert sum(r.name == "app.http" for r in caplog.records) == 1
