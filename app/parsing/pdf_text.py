"""PDF -> per-page text, with running headers and footers removed."""

import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import pymupdf

# A line repeated on at least this share of pages (and at least MIN_REPEAT_PAGES
# pages) is a running header/footer, e.g. "NOTICE OF 114TH AGM" or a CIN line.
REPEAT_SHARE = 0.3
MIN_REPEAT_PAGES = 3

_PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")
_LETTERS = re.compile(r"[a-z]")
# Bullet glyphs and other control characters PyMuPDF emits (tabs/newlines kept).
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# Running headers carry words; bare markers like "1." repeat too but are content.
MIN_HEADER_LETTERS = 4


def extract_pages(source: Path | bytes) -> list[str]:
    """Plain text of every page, in reading order."""
    doc = (
        pymupdf.open(stream=source, filetype="pdf")  # type: ignore[no-untyped-call]
        if isinstance(source, bytes)
        else pymupdf.open(source)  # type: ignore[no-untyped-call]
    )
    pages: list[str] = []
    with doc:
        for index in range(doc.page_count):
            page = doc.load_page(index)  # type: ignore[no-untyped-call]
            pages.append(_CONTROL_CHARS.sub("", page.get_text("text")))
    return pages


def _signature(line: str) -> str:
    """Line identity for repeat detection: digits masked so page numbers match."""
    return _DIGITS.sub("#", " ".join(line.split())).lower()


def strip_running_lines(pages: Sequence[str]) -> list[str]:
    """Remove page-number lines and lines that repeat across many pages."""
    seen_on: Counter[str] = Counter()
    for page in pages:
        seen_on.update({_signature(line) for line in page.splitlines() if line.strip()})
    threshold = max(MIN_REPEAT_PAGES, int(len(pages) * REPEAT_SHARE))
    repeated = {
        sig
        for sig, count in seen_on.items()
        if count >= threshold and len(_LETTERS.findall(sig)) >= MIN_HEADER_LETTERS
    }

    cleaned: list[str] = []
    for page in pages:
        kept = [
            line
            for line in page.splitlines()
            if not _PAGE_NUMBER.match(line) and _signature(line) not in repeated
        ]
        cleaned.append("\n".join(kept))
    return cleaned
