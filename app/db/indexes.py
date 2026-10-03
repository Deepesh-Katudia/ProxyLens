"""Atlas Vector Search / Atlas Search index definitions and creation."""

import asyncio
import logging
from typing import Any

from pymongo.asynchronous.collection import AsyncCollection
from pymongo.operations import SearchIndexModel

from app.db.client import Document
from app.db.collections import REGULATIONS_TEXT_INDEX, REGULATIONS_VECTOR_INDEX

logger = logging.getLogger(__name__)

POLL_SECONDS = 5


def vector_index_definition(dim: int) -> dict[str, Any]:
    return {
        "fields": [
            {"type": "vector", "path": "embedding", "numDimensions": dim, "similarity": "cosine"},
            {"type": "filter", "path": "applies_to"},
            {"type": "filter", "path": "source"},
        ]
    }


def text_index_definition() -> dict[str, Any]:
    return {
        "mappings": {
            "dynamic": False,
            "fields": {
                "text": {"type": "string", "analyzer": "lucene.english"},
                "citation": {"type": "string"},
                "heading": {"type": "string", "analyzer": "lucene.english"},
                "applies_to": {"type": "token"},
                "source": {"type": "token"},
            },
        }
    }


def regulation_index_models(dim: int, *, with_text: bool) -> list[SearchIndexModel]:
    models = [
        SearchIndexModel(
            definition=vector_index_definition(dim),
            name=REGULATIONS_VECTOR_INDEX,
            type="vectorSearch",
        )
    ]
    if with_text:
        models.append(
            SearchIndexModel(
                definition=text_index_definition(), name=REGULATIONS_TEXT_INDEX, type="search"
            )
        )
    return models


async def ensure_search_indexes(
    collection: AsyncCollection[Document],
    models: list[SearchIndexModel],
) -> None:
    """Create missing indexes and update existing ones to the current definition."""
    existing = {idx["name"] async for idx in await collection.list_search_indexes()}
    for model in models:
        name = model.document["name"]
        if name in existing:
            logger.info("Updating search index %s", name)
            await collection.update_search_index(name, model.document["definition"])
        else:
            logger.info("Creating search index %s", name)
            await collection.create_search_index(model)


async def wait_until_queryable(
    collection: AsyncCollection[Document],
    names: list[str],
    timeout_s: float = 600,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        statuses = {
            idx["name"]: bool(idx.get("queryable"))
            async for idx in await collection.list_search_indexes()
        }
        pending = [n for n in names if not statuses.get(n)]
        if not pending:
            return
        if loop.time() > deadline:
            raise TimeoutError(f"search indexes not queryable after {timeout_s}s: {pending}")
        logger.info("Waiting for indexes to become queryable: %s", pending)
        await asyncio.sleep(POLL_SECONDS)
