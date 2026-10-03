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
from app.parsing.notice import parse_notice_pdf
from app.parsing.pdf_text import extract_pages
from scripts.collect_notices import MANIFEST, NOTICES_DIR, REQUEST_PAUSE_S

logger = logging.getLogger("harvest_notices")

REJECTED = NOTICES_DIR / "rejected.txt"
MAX_BYTES = 40_000_000
TIMEOUT_S = 120
MAX_ITEMS = 30  # real notices rarely exceed ~20 items; more means the splitter misfired
_COMPANY = re.compile(
    r"(?i:members|shareholders)\s+(?i:of)\s+(?:M/s\.?\s*)?(?:(?i:the)\s+)?"
    r"([A-Z][A-Za-z0-9&.,()'\- ]{2,90}?\b(?:LIMITED|Limited|LTD|Ltd)\b\.?)"
)
_NOTICE_START = re.compile(r"hereby\s+given", re.IGNORECASE)
OPENING_CHARS = 600  # the notice's first sentence names the issuer
_ANY_COMPANY = re.compile(
    r"\b([A-Z][A-Za-z0-9&.'\- ]{1,60}?\s(?:LIMITED|Limited|LTD\.?|Ltd\.?))(?![A-Za-z])"
)
# Names that appear in nearly every notice but are not the issuer.
_NOT_ISSUER = re.compile(
    r"stock exchange|bse|depositor|central depository|kfin|intime|link|registrar|"
    r"bigshare|cameo|skyline|purva|beetal|niche|maheshwari|adroit|alankit|"
    r"satellite|abhipra|in favour|private limited|pvt",
    re.IGNORECASE,
)
FIRST_PAGES_FOR_NAME = 3


_LEADING_FILLER = frozenset(
    {"for", "resolved", "that", "agm", "egm", "notice", "of", "the", "members",
     "shareholders", "m/s", "m/s.", "to", "and", "by", "order", "board"}
)  # fmt: skip


_NAME_CONNECTORS = frozenset({"of", "and", "&", "the"})


def _clean_name(name: str) -> str:
    """Keep the capitalised run before "Limited": drop prose ("Thanking you Yours
    faithfully For"), filler ("RESOLVED THAT") and numbering ("AGM Notice 2024-25 01")."""
    tokens = name.strip(" ,.").split()
    lowercase = [
        i for i, t in enumerate(tokens[:-1]) if t[:1].islower() and t not in _NAME_CONNECTORS
    ]
    if lowercase:
        tokens = tokens[lowercase[-1] + 1 :]
    while len(tokens) > 2 and (
        tokens[0].lower() in _LEADING_FILLER or any(c.isdigit() for c in tokens[0])
    ):
        tokens = tokens[1:]
    return " ".join(tokens)


def guess_company(pages: list[str]) -> str:
    """Issuer name: the 'Members of XYZ Limited' phrase, else the most frequent
    '... Limited' on the first pages that isn't an exchange, depository or registrar."""
    text = " ".join(" ".join(pages).split())
    start = _NOTICE_START.search(text)
    opening = text[start.start() : start.start() + OPENING_CHARS] if start else ""
    for scope in (opening, text):
        match = _COMPANY.search(scope)
        if match and not _NOT_ISSUER.search(_clean_name(match.group(1))):
            return _clean_name(match.group(1))
    head = " ".join(" ".join(pages[:FIRST_PAGES_FOR_NAME]).split())
    names = [_clean_name(m) for m in _ANY_COMPANY.findall(head)]
    names = [n for n in names if not _NOT_ISSUER.search(n) and len(n.split()) >= 2]
    if not names:
        return ""
    counts: dict[str, int] = {}
    for name in names:
        key = name.upper().rstrip(".")
        counts[key] = counts.get(key, 0) + 1
    best = max(counts, key=lambda k: counts[k])
    return next(n for n in names if n.upper().rstrip(".") == best)


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
