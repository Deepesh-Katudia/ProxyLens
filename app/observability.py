"""Structured logging, request IDs and per-node latency (SPEC Phase 8).

In JSON mode every log line is one JSON object with the fields Cloud Logging reads
(`severity`, `message`, `time`), plus the current request ID and any `extra=` fields.
The request ID comes from the `X-Request-ID` header (or is generated), is echoed on
the response, and is bound for the background job that request starts, so a job's
node-latency lines can be found from the upload that caused them.
"""

import inspect
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, TypeVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
LogFormat = Literal["text", "json"]

_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else came from `extra=`.
_RECORD_FIELDS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
}
_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

node_logger = logging.getLogger("app.pipeline.graph")
http_logger = logging.getLogger("app.http")

State = TypeVar("State", contravariant=True)


class Node(Protocol[State]):
    """A LangGraph node: LangGraph's own node protocol names the parameter `state`."""

    def __call__(self, state: State) -> Any: ...


def new_request_id() -> str:
    return uuid.uuid4().hex


def clean_request_id(value: str | None) -> str:
    """Keep a caller's ID only if it is short and log-safe; otherwise make a new one."""
    if value and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return new_request_id()


def current_request_id() -> str | None:
    return _request_id.get()


@contextmanager
def bind_request_id(request_id: str | None) -> Iterator[None]:
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, in the shape Cloud Logging parses."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logger": record.name,
        }
        request_id = getattr(record, "request_id", None) or current_request_id()
        if request_id:
            payload["request_id"] = request_id
        payload |= {k: v for k, v in vars(record).items() if k not in _RECORD_FIELDS}
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str, fmt: LogFormat) -> None:
    """Install a single stderr handler on the root logger; safe to call repeatedly."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_proxylens", False)]:
        root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler._proxylens = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter(_TEXT_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)


class RequestIdMiddleware:
    """Bind a request ID for the whole request (background tasks included), echo it
    on the response, and log one access line with the request's latency."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.lower().encode())
        request_id = clean_request_id(incoming.decode("latin-1") if incoming else None)
        status_code = 500
        started = time.perf_counter()
        logged = False

        def log_access() -> None:
            nonlocal logged
            logged = True
            path = scope["path"]
            http_logger.log(
                logging.DEBUG if path.endswith("/healthz") else logging.INFO,
                "%s %r %d",  # %r: a percent-decoded path may contain newlines
                scope["method"],
                path,
                status_code,
                extra={
                    "method": scope["method"],
                    "path": path,
                    "status": status_code,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                },
            )

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)
            # Log when the response is complete: background tasks (a whole analysis
            # job) run after this inside the same app call and must not count.
            if message["type"] == "http.response.body" and not message.get("more_body"):
                log_access()

        with bind_request_id(request_id):
            try:
                await self.app(scope, receive, send_with_id)
            finally:
                if not logged:  # failed before the response finished
                    log_access()


def _log_node(name: str, started: float, failed: bool) -> None:
    node_logger.log(
        logging.ERROR if failed else logging.INFO,
        "node %s %s",
        name,
        "failed" if failed else "done",
        extra={
            "node": name,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "request_id": current_request_id(),
        },
    )


def timed_node(name: str, fn: Callable[[State], Any]) -> Node[State]:
    """Wrap a LangGraph node (sync or async) so each run logs its name, latency and
    request ID."""
    if inspect.iscoroutinefunction(fn):

        async def run_async(state: State) -> Any:
            started = time.perf_counter()
            try:
                result = await fn(state)
            except Exception:
                _log_node(name, started, failed=True)
                raise
            _log_node(name, started, failed=False)
            return result

        return run_async

    def run_sync(state: State) -> Any:
        started = time.perf_counter()
        try:
            result = fn(state)
        except Exception:
            _log_node(name, started, failed=True)
            raise
        _log_node(name, started, failed=False)
        return result

    return run_sync
