"""Turn raw PDF page text from gazette-style legal PDFs into clean body text.

The consolidated SEBI / MCA PDFs carry three kinds of noise:
- a page number on the first line of each page;
- an amendment-history footnote block under a long run of spaces;
- inline amendment markers such as ``134[Provided ...]`` or ``[***]``.
"""

import re
from collections.abc import Iterable

_FOOTNOTE_SEPARATOR = re.compile(r"^ {20,}$", re.MULTILINE)
_PAGE_NUMBER_LINE = re.compile(r"^\s*\d{1,4}\s*$")

# Order matters: drop whole omissions before stripping individual brackets.
_OMISSION = re.compile(r"\d{0,3}\s?\[\s?\*\*\*\s?\]\s?\d{0,3}")
_LEADING_MARKER = re.compile(r"(?<![\w(])\d{1,3}\s?(?=[\[{])")
_TRAILING_MARKER = re.compile(r"(?<=[\]}])\s?\d{1,3}(?=[\s.,:;)]|$)")
_BRACKETS = re.compile(r"[\[\]{}]")
_SPACES = re.compile("[ \t\N{NO-BREAK SPACE}]+")
_SPACE_BEFORE_PUNCT = re.compile(r" +(?=[:;,.])")


def strip_page(page_text: str) -> str:
    """Drop the footnote block and the leading page-number line from one page."""
    match = _FOOTNOTE_SEPARATOR.search(page_text)
    body = page_text[: match.start()] if match else page_text
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if _PAGE_NUMBER_LINE.match(line):
            lines = lines[i + 1 :]
        break
    return "\n".join(lines)


def remove_amendment_markers(text: str) -> str:
    """Remove footnote numbers and amendment brackets, keeping the operative words."""
    text = _OMISSION.sub(" ", text)
    text = _LEADING_MARKER.sub("", text)
    text = _TRAILING_MARKER.sub("", text)
    return _BRACKETS.sub("", text)


def normalize_lines(text: str) -> list[str]:
    """Collapse runs of spaces per line; blank lines become empty strings."""
    return [
        _SPACE_BEFORE_PUNCT.sub("", _SPACES.sub(" ", line)).strip() for line in text.splitlines()
    ]


def clean_pages(pages: Iterable[str]) -> list[str]:
    """Full cleaning pass over a document's pages; returns normalized lines."""
    body = "\n".join(strip_page(p) for p in pages)
    return normalize_lines(remove_amendment_markers(body))


def join_lines(lines: Iterable[str]) -> str:
    """Join wrapped lines into one paragraph, mending words hyphenated across lines."""
    out = ""
    for line in lines:
        if not line:
            continue
        if not out:
            out = line
        elif out.endswith("-") and not out.endswith(" -"):
            out += line
        else:
            out += " " + line
    return out
