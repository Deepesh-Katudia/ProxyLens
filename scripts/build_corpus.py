"""Build the regulation corpus: parse -> chunk -> tag -> embed -> upsert.

    uv run python -m scripts.build_corpus             # full build into MongoDB
    uv run python -m scripts.build_corpus --dry-run   # parse only, write JSONL

Both sources are downloaded once and cached under data/raw/regulations/:
SEBI LODR from sebi.gov.in, and the Companies Act 2013 as enacted from PRS India
(India Code and MCA block automated downloads, so no amended text is available).
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import pymupdf

from app.config import get_settings
from app.corpus import companies_act
from app.corpus.companies_act import Page, TextLine, build_companies_act_chunks
from app.corpus.lodr import build_lodr_chunks, lodr_doc
from app.corpus.sources import LODR_PAGE_URL, LODR_PDF_URL, amended_up_to, download_cached
from app.corpus.tagging import load_tag_map
from app.db.client import create_client
from app.db.collections import REGULATIONS
from app.db.regulations import upsert_chunks
from app.retrieval.embeddings import create_embedder
from app.schemas.regulation import RegulationChunk

logger = logging.getLogger("build_corpus")

RAW_DIR = Path("data/raw/regulations")
LODR_PDF = RAW_DIR / "sebi_lodr_2015.pdf"
COMPANIES_ACT_PDF = RAW_DIR / "companies_act_2013.pdf"
PROCESSED_JSONL = Path("data/processed/regulations.jsonl")


def read_pages(pdf_path: Path) -> list[str]:
    with pymupdf.open(pdf_path) as doc:  # type: ignore[no-untyped-call]
        return [page.get_text() for page in doc]


def read_layout(pdf_path: Path) -> list[Page]:
    """Text lines with geometry, grouped by block, for margin-heading layouts."""
    pages: list[Page] = []
    with pymupdf.open(pdf_path) as doc:  # type: ignore[no-untyped-call]
        for page in doc:
            blocks = []
            for block in page.get_text("dict")["blocks"]:
                lines = [
                    TextLine(
                        x0=line["bbox"][0],
                        y0=line["bbox"][1],
                        x1=line["bbox"][2],
                        text="".join(span["text"] for span in line["spans"]),
                    )
                    for line in block.get("lines", [])
                ]
                if lines:
                    blocks.append(lines)
            pages.append(blocks)
    return pages


def parse_lodr() -> list[RegulationChunk]:
    pages = read_pages(download_cached(LODR_PDF_URL, LODR_PDF))
    as_of = amended_up_to(pages[0])
    if as_of is None:
        raise ValueError("could not find the 'Amended up to' date on page 1 of the LODR PDF")
    chunks = build_lodr_chunks(pages, lodr_doc(LODR_PAGE_URL, as_of), load_tag_map())
    logger.info("SEBI LODR (as of %s): %d chunks", as_of, len(chunks))
    return chunks


def parse_companies_act() -> list[RegulationChunk]:
    pdf = download_cached(companies_act.SOURCE_URL, COMPANIES_ACT_PDF)
    chunks = build_companies_act_chunks(read_layout(pdf), load_tag_map())
    logger.warning("Companies Act 2013: %d chunks from the 2013 as-enacted text", len(chunks))
    return chunks


def write_jsonl(chunks: list[RegulationChunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            row = chunk.model_dump(by_alias=True, mode="json", exclude={"embedding"})
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    logger.info("Wrote %s", path)


async def embed_and_upsert(chunks: list[RegulationChunk]) -> None:
    settings = get_settings()
    client = create_client(settings)
    if client is None:
        raise SystemExit("MONGODB_URI is not set; use --dry-run or configure .env")
    embedder = create_embedder(settings)
    vectors = embedder.embed_documents([c.embedding_text() for c in chunks])
    embedded = [c.model_copy(update={"embedding": v}) for c, v in zip(chunks, vectors, strict=True)]
    try:
        written, deleted = await upsert_chunks(client[settings.mongodb_db][REGULATIONS], embedded)
        logger.info("Stored %d chunks, deleted %d stale", written, deleted)
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="parse and write JSONL only")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    chunks = parse_lodr() + parse_companies_act()
    ids = [c.id for c in chunks]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate chunk ids; refusing to upsert")
    write_jsonl(chunks, PROCESSED_JSONL)
    if not args.dry_run:
        asyncio.run(embed_and_upsert(chunks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
