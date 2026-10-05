"""FastAPI app factory."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import APIRouter, FastAPI
from pymongo.errors import PyMongoError

from app import __version__
from app.api import documents, gold, health, regulations
from app.config import Settings, get_settings
from app.db.client import create_client
from app.db.collections import REGULATIONS
from app.gold.store import GoldStore
from app.observability import RequestIdMiddleware, configure_logging
from app.pipeline.factory import PipelineFactory
from app.pipeline.graph import atlas_retriever
from app.reports.runner import JobRunner
from app.reports.store import InMemoryReportStore, MongoReportStore, ReportStore
from app.retrieval.embeddings import Embedder, create_embedder
from app.rules.engine import load_policy
from app.schemas.regulation import RegulationHit
from app.schemas.resolution import ResolutionType

API_PREFIX = "/api/v1"

logger = logging.getLogger(__name__)


async def _no_retrieval(
    query: str, resolution_type: ResolutionType | None, k: int
) -> list[RegulationHit]:
    raise RuntimeError("MONGODB_URI is not set; regulation retrieval is unavailable")


class WarmUp(Protocol):
    def warm_up(self) -> None: ...


def preload(embedder: Embedder, factory: WarmUp) -> None:
    """Load the embedder and the student so the first upload doesn't wait for them
    (BGE ~12 s, GGUF longer). Failures are logged: the models load lazily anyway."""
    for name, load in (
        ("embedder", lambda: embedder.embed_query("warm up")),
        ("student", factory.warm_up),
    ):
        try:
            load()
            logger.info("preloaded %s", name)
        except Exception:
            logger.exception("preload failed for %s; it will load on first use", name)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = create_client(settings)
        app.state.db = client[settings.mongodb_db] if client is not None else None
        # The embedder loads its model on first query, so startup stays fast.
        app.state.embedder = create_embedder(settings)
        app.state.gold_store = GoldStore()
        store: ReportStore
        if app.state.db is not None:
            mongo_store = MongoReportStore(app.state.db)
            try:
                await mongo_store.ensure_indexes()
            except PyMongoError:
                logger.exception("could not create report indexes; continuing")
            store = mongo_store
        else:
            store = InMemoryReportStore()  # local runs without MongoDB; lost on restart
        app.state.report_store = store
        retriever = (
            atlas_retriever(app.state.db[REGULATIONS], app.state.embedder)
            if app.state.db is not None
            else _no_retrieval
        )
        app.state.pipeline_factory = PipelineFactory(settings, retriever, load_policy())
        app.state.job_runner = JobRunner(store, app.state.pipeline_factory)
        warm = (
            asyncio.create_task(
                asyncio.to_thread(preload, app.state.embedder, app.state.pipeline_factory)
            )
            if settings.preload_models
            else None
        )
        try:
            yield
        finally:
            if warm is not None:
                warm.cancel()  # a load already running in its thread finishes on its own
            if client is not None:
                await client.close()

    app = FastAPI(title="ProxyLens", version=__version__, lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(regulations.router)
    api.include_router(gold.router)
    api.include_router(documents.router)
    app.include_router(api)
    # Unprefixed alias so Cloud Run and compose health checks can hit /healthz.
    app.include_router(health.router)
    return app


app = create_app()
