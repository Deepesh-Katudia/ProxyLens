"""Maintain the notice collection in data/raw/notices/ (SPEC 7.2 step 1).

    uv run python -m scripts.collect_notices              # sync manifest with the folder
    uv run python -m scripts.collect_notices --download   # also fetch rows that have a URL

Manual mode: drop PDFs into data/raw/notices/ and fill in `company` (required
for the company-grouped split) in manifest.csv. Rows can also be added with a
`source_url` and no file yet; --download fetches them politely (one at a time,
a pause between requests, an identifying User-Agent, cached on disk).
"""

import argparse
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

from app.corpus.sources import download_cached
from app.dataset.manifest import NoticeEntry, file_sha256, read_manifest, write_manifest

logger = logging.getLogger("collect_notices")

NOTICES_DIR = Path("data/raw/notices")
MANIFEST = NOTICES_DIR / "manifest.csv"
REQUEST_PAUSE_S = 2.0


def sync(entries: list[NoticeEntry], download: bool) -> list[NoticeEntry]:
    by_file = {e.file: e for e in entries}
    for path in sorted(NOTICES_DIR.glob("*.pdf")):
        by_file.setdefault(path.name, NoticeEntry(file=path.name))

    synced: list[NoticeEntry] = []
    for entry in by_file.values():
        path = NOTICES_DIR / entry.file
        if not path.exists() and download and entry.source_url:
            try:
                download_cached(entry.source_url, path)
            except Exception as exc:  # keep going; one bad URL shouldn't stop the batch
                logger.error("%s: download failed: %s", entry.file, exc)
            time.sleep(REQUEST_PAUSE_S)
        if path.exists() and not entry.sha256:
            entry = replace(entry, sha256=file_sha256(path))
        synced.append(entry)
    return synced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="fetch rows with a source_url")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    entries = sync(read_manifest(MANIFEST), args.download)
    write_manifest(MANIFEST, entries)
    present = [e for e in entries if (NOTICES_DIR / e.file).exists()]
    missing_company = [e.file for e in present if not e.company]
    logger.info("%d notices in manifest, %d PDFs on disk", len(entries), len(present))
    if missing_company:
        logger.warning(
            "%d rows need a company name: %s", len(missing_company), missing_company[:10]
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
