"""Rebuild tests/fixtures/notices/*.pdf from source notices listed in the manifest.

    uv run python -m scripts.make_notice_fixtures

Downloads each `source_url` once (cached in data/raw/notices/), downsamples
embedded images to keep the repo small, and keeps the compressed copy only if
its extracted text is identical to the original's; otherwise the original is used.
"""

import logging
import shutil
import sys
from pathlib import Path

import pymupdf
import yaml

from app.corpus.sources import download_cached
from app.parsing.pdf_text import extract_pages

logger = logging.getLogger("make_notice_fixtures")

FIXTURES = Path("tests/fixtures/notices")
CACHE = Path("data/raw/notices")
IMAGE_DPI_THRESHOLD = 100
IMAGE_DPI_TARGET = 60
IMAGE_QUALITY = 40


def compress(src: Path, dst: Path) -> bool:
    """Write a smaller copy of `src`; True if its text survived unchanged."""
    with pymupdf.open(src) as doc:  # type: ignore[no-untyped-call]
        doc.rewrite_images(
            dpi_threshold=IMAGE_DPI_THRESHOLD, dpi_target=IMAGE_DPI_TARGET, quality=IMAGE_QUALITY
        )
        doc.save(dst, garbage=3, deflate=True)
    return extract_pages(src) == extract_pages(dst)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    manifest = yaml.safe_load((FIXTURES / "manifest.yaml").read_text(encoding="utf-8"))
    for entry in manifest["notices"]:
        src = download_cached(entry["source_url"], CACHE / entry["file"])
        dst = FIXTURES / entry["file"]
        if not compress(src, dst):
            shutil.copyfile(src, dst)
            logger.info("%s: kept original (compression changed its text)", entry["file"])
        logger.info("%s: %.2f MB", entry["file"], dst.stat().st_size / 1e6)
    return 0


if __name__ == "__main__":
    sys.exit(main())
