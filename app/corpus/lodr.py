"""Build corpus chunks from the consolidated SEBI LODR 2015 PDF."""

from collections.abc import Iterable

from app.corpus.builder import SourceDoc, schedule_chunks, slice_between, unit_chunks
from app.corpus.clean import clean_pages
from app.corpus.tagging import TagMap
from app.corpus.units import parse_units
from app.schemas.regulation import RegulationChunk, RegulationSource

# Chapters I-IV cover listed entities with equity shares; later chapters deal
# with debt, mutual funds, etc., which AGM resolutions don't touch.
LAST_CHAPTER_EXCLUSIVE = "CHAPTER V"


def lodr_doc(source_url: str, as_of: str) -> SourceDoc:
    return SourceDoc(
        source=RegulationSource.SEBI_LODR_2015,
        short_name="SEBI LODR 2015",
        unit_label="Regulation",
        id_prefix="lodr",
        key_prefix="reg",
        source_url=source_url,
        as_of=as_of,
    )


def build_lodr_chunks(pages: Iterable[str], doc: SourceDoc, tags: TagMap) -> list[RegulationChunk]:
    lines = clean_pages(pages)
    body = lines[: lines.index(LAST_CHAPTER_EXCLUSIVE)]
    chunks = unit_chunks(parse_units(body), doc, tags)

    schedule_2 = slice_between(
        lines,
        lambda s: s.upper().startswith("SCHEDULE II:"),
        lambda s: s.upper().startswith("SCHEDULE III"),
    )
    chunks += schedule_chunks(schedule_2, "II", doc, tags)

    schedule_12 = slice_between(
        lines,
        lambda s: s.upper().startswith("SCHEDULE XII"),
        lambda s: s.startswith("U.K. SINHA") or s.startswith("Note:"),
    )
    chunks += schedule_chunks(schedule_12, "XII", doc, tags)
    return chunks
