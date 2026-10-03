"""MongoDB client lifecycle and connectivity helpers."""

import logging
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.config import Settings

logger = logging.getLogger(__name__)

Document = dict[str, Any]


def create_client(settings: Settings) -> AsyncMongoClient[Document] | None:
    """Build a client, or return None when no URI is configured.

    The client connects lazily, so this never blocks on the network.
    """
    uri = settings.mongodb_uri.get_secret_value()
    if not uri:
        logger.warning("MONGODB_URI is not set; database features are disabled")
        return None
    return AsyncMongoClient(
        uri,
        serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
        appname="proxylens",
    )


async def ping(db: AsyncDatabase[Document]) -> bool:
    """Return True if the database answers a ping."""
    try:
        await db.command("ping")
    except PyMongoError:
        logger.exception("MongoDB ping failed")
        return False
    return True
