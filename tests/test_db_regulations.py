"""upsert_chunks against a small in-memory collection.

mongomock-motor can't execute PyMongo 4.x `ReplaceOne` (it rejects the `sort`
argument newer PyMongo passes), so this fake implements just the calls used.
"""

from dataclasses import dataclass
from typing import Any

from pymongo import ReplaceOne

from app.db.regulations import upsert_chunks
from app.schemas.regulation import RegulationChunk, RegulationSource


@dataclass
class _BulkResult:
    upserted_count: int
    matched_count: int


@dataclass
class _DeleteResult:
    deleted_count: int


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def bulk_write(self, ops: list[ReplaceOne[Any]], ordered: bool) -> _BulkResult:
        upserted = matched = 0
        for op in ops:
            doc_id = op._filter["_id"]
            matched += doc_id in self.docs
            upserted += doc_id not in self.docs
            self.docs[doc_id] = dict(op._doc)
        return _BulkResult(upserted, matched)

    async def delete_many(self, query: dict[str, Any]) -> _DeleteResult:
        sources, keep = set(query["source"]["$in"]), set(query["_id"]["$nin"])
        stale = [k for k, d in self.docs.items() if d["source"] in sources and k not in keep]
        for key in stale:
            del self.docs[key]
        return _DeleteResult(len(stale))


def _chunk(
    chunk_id: str, source: RegulationSource = RegulationSource.SEBI_LODR_2015
) -> RegulationChunk:
    return RegulationChunk(
        id=chunk_id,
        source=source,
        citation=chunk_id,
        section_path=[],
        text="some legal text here",
        source_url="https://example.test",
        as_of="2026-07-14",
        embedding=[0.1, 0.2],
    )


async def test_upsert_replaces_and_prunes_stale_chunks_of_same_source() -> None:
    collection = FakeCollection()
    await upsert_chunks(
        collection,  # type: ignore[arg-type]
        [_chunk("a"), _chunk("old"), _chunk("ca_1", RegulationSource.COMPANIES_ACT_2013)],
    )

    stored, deleted = await upsert_chunks(collection, [_chunk("a"), _chunk("b")])  # type: ignore[arg-type]

    assert sorted(collection.docs) == ["a", "b", "ca_1"]  # other sources untouched
    assert (stored, deleted) == (2, 1)
    assert collection.docs["a"]["_id"] == "a"  # stored under the Mongo key, not "id"
    assert collection.docs["a"]["embedding"] == [0.1, 0.2]


async def test_upsert_of_nothing_is_a_no_op() -> None:
    assert await upsert_chunks(FakeCollection(), []) == (0, 0)  # type: ignore[arg-type]
