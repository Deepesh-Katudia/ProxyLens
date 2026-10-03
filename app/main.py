"""FastAPI app factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app import __version__
from app.api import health, regulations
from app.config import Settings, get_settings
from app.db.client import create_client
from app.retrieval.embeddings import create_embedder

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = create_client(settings)
        app.state.db = client[settings.mongodb_db] if client is not None else None
        # The embedder loads its model on first query, so startup stays fast.
        app.state.embedder = create_embedder(settings)
        try:
            yield
        finally:
            if client is not None:
                await client.close()

    app = FastAPI(title="ProxyLens", version=__version__, lifespan=lifespan)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(regulations.router)
    app.include_router(api)
    # Unprefixed alias so Cloud Run and compose health checks can hit /healthz.
    app.include_router(health.router)
    return app


app = create_app()
