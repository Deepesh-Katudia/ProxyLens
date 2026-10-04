"""Add notices from a list of candidate PDF URLs to the collection.

    uv run python -m scripts.harvest_notices urls.txt

Each URL is downloaded politely (one at a time, a pause between requests, an
identifying User-Agent). A file is kept only if it parses as a notice with at
least one agenda item; the company name is read from the notice text. Rejected
URLs are logged with the reason and never retried (data/raw/notices/rejected.txt).
"""

import argparse
import hashlib
import logging
import re
import sys
import time
from pathlib import Path

import httpx

from app.corpus.sources import USER_AGENT
from app.dataset.manifest import NoticeEntry, file_sha256, read_manifest, write_manifest
from app.parsing.company import guess_company
from app.parsing.notice import parse_notice_pdf
from app.parsing.pdf_text import extract_pages
from scripts.collect_notices import MANIFEST, NOTICES_DIR, REQUEST_PAUSE_S

logger = logging.getLogger("harvest_notices")

REJECTED = NOTICES_DIR / "rejected.txt"
MAX_BYTES = 40_000_000
TIMEOUT_S = 120
MAX_ITEMS = 30  # real notices rarely exceed ~20 items; more means the splitter misfired
_NEWSPAPER = re.compile(
    r"\b(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)\b|financial\s*express|"
    r"business\s*standard|free\s+press\s+journal|jansatta|navshakti|loksatta|e-?paper|newspaper",
    re.IGNORECASE,
)
MAX_AD_PAGES = 3
MIN_NEWSPAPER_MARKERS = 5


def looks_like_newspaper_ad(pages: list[str]) -> bool:
    """Short filings of newspaper clippings: abbreviated, often several companies per page."""
    if len(pages) > MAX_AD_PAGES:
        return False
    text = " ".join(pages)
    if len(_NEWSPAPER.findall(text)) >= MIN_NEWSPAPER_MARKERS:
        return True
    return len(pages) == 1 and "explanatory statement" not in text.lower()


def _filename(url: str, company: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", company.lower()).strip("_")[:40] or "notice"
    return f"{slug}_{hashlib.sha256(url.encode()).hexdigest()[:8]}.pdf"


def fetch(client: httpx.Client, url: str) -> bytes:
    response = client.get(url)
    response.raise_for_status()
    if len(response.content) > MAX_BYTES:
        raise ValueError(f"too large ({len(response.content) / 1e6:.0f} MB)")
    if not response.content.startswith(b"%PDF"):
        raise ValueError("not a PDF")
    return response.content


def harvest(urls: list[str]) -> tuple[int, int]:
    entries = read_manifest(MANIFEST)
    known_urls = {e.source_url for e in entries}
    known_hashes = {e.sha256 for e in entries}
    rejected = set(REJECTED.read_text(encoding="utf-8").split()) if REJECTED.exists() else set()
    added = failed = 0

    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S, follow_redirects=True
    ) as client:
        for url in urls:
            if url in known_urls or url in rejected:
                continue
            try:
                content = fetch(client, url)
                pages = extract_pages(content)
                if looks_like_newspaper_ad(pages):
                    raise ValueError("newspaper advertisement, not the notice itself")
                notice = parse_notice_pdf(content)
                if not notice.items:
                    raise ValueError("no agenda items found")
                if len(notice.items) > MAX_ITEMS:
                    raise ValueError(f"{len(notice.items)} items: likely a parsing failure")
                company = guess_company(pages)
                digest = hashlib.sha256(content).hexdigest()
                if digest in known_hashes:
                    raise ValueError("duplicate of a notice already collected")
            except Exception as exc:  # any failure just rejects this URL
                logger.info("reject %s: %s", url, exc)
                with REJECTED.open("a", encoding="utf-8") as fh:
                    fh.write(f"{url}\n")
                failed += 1
            else:
                path = NOTICES_DIR / _filename(url, company)
                path.write_bytes(content)
                entries.append(
                    NoticeEntry(
                        file=path.name,
                        company=company,
                        meeting_type=notice.meeting_type.value,
                        source_url=url,
                        sha256=file_sha256(path),
                    )
                )
                known_hashes.add(digest)
                added += 1
                logger.info("added %s (%s, %d items)", path.name, company, len(notice.items))
            time.sleep(REQUEST_PAUSE_S)
    write_manifest(MANIFEST, entries)
    return added, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls_file", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    urls = [u.strip() for u in args.urls_file.read_text(encoding="utf-8").split() if u.strip()]
    added, failed = harvest(list(dict.fromkeys(urls)))
    total = len(read_manifest(MANIFEST))
    logger.info("added %d, rejected %d; manifest now has %d notices", added, failed, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
