"""Persistence for the `regulations` corpus."""

from collections.abc import Sequence

from pymongo import ReplaceOne
from pymongo.asynchronous.collection import AsyncCollection

from app.db.client import Document
from app.schemas.regulation import RegulationChunk, RegulationSource


async def upsert_chunks(
    collection: AsyncCollection[Document],
    chunks: Sequence[RegulationChunk],
) -> tuple[int, int]:
    """Replace each chunk by `_id`, then delete stale chunks of the same sources.

    Returns (stored, deleted): `stored` counts inserted plus matched documents.
    """
    if not chunks:
        return 0, 0
    ops = [
        ReplaceOne({"_id": c.id}, c.model_dump(by_alias=True, mode="json"), upsert=True)
        for c in chunks
    ]
    result = await collection.bulk_write(ops, ordered=False)

    sources: set[RegulationSource] = {c.source for c in chunks}
    stale = await collection.delete_many(
        {"source": {"$in": [s.value for s in sources]}, "_id": {"$nin": [c.id for c in chunks]}}
    )
    return result.upserted_count + result.matched_count, stale.deleted_count
