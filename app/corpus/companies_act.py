"""Build corpus chunks from the Companies Act, 2013 Gazette PDF (PRS India copy).

The Gazette layout puts each section's heading in the page margin, beside the
section's first line. Each page is rebuilt from line geometry: main-column
lines become text, and a margin note level with a section's first line becomes
that section's heading line (the shape `parse_units` expects).

This copy is the Act as enacted on 29 Aug 2013. Every chunk carries a note
saying so, because several sections used here were amended later.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from app.corpus.builder import SourceDoc, schedule_chunks, slice_between, unit_chunks
from app.corpus.clean import normalize_lines
from app.corpus.tagging import TagMap
from app.corpus.units import parse_units
from app.schemas.regulation import RegulationChunk, RegulationSource

SOURCE_URL = "https://prsindia.org/files/bills_acts/acts_parliament/2013/companies-act,-2013.pdf"
AS_ENACTED = "2013-08-29"
PRE_AMENDMENT_NOTE = (
    "Text as enacted on 29 Aug 2013 (PRS India copy). Later amendments, e.g. the "
    "Companies (Amendment) Acts of 2015, 2017 and 2020, are not reflected; verify "
    "against the current Act before relying on it."
)

# Sections that AGM/EGM resolutions most often turn on (SPEC Phase 1, plus
# 14, 42, 62, 123, 142 and 148 so every resolution type has governing text).
SECTIONS = frozenset(
    {"14", "42", "62", "102", "123", "139", "142", "148", "149", "152", "160",
     "177", "178", "180", "188", "196", "197"}
)  # fmt: skip
SCHEDULES = ("IV", "V")

# Page geometry of the Gazette PDF (points, A4 width 595).
MAIN_COLUMN_LEFT = 110.0
MAIN_COLUMN_RIGHT = 485.0
HEADING_Y_TOLERANCE = 12.0
MARGIN_LINE_GAP = 14.0  # max vertical step between lines of one margin note
HEADER_MAX_Y = 90.0  # running Gazette header (page number, title, part) sits above this

_SECTION_START = re.compile(r"^\s*\d{1,3}[A-Z]{0,2}\.\s")
_ACT_REFERENCE = re.compile(r"^\d+ of \d{4}\.?$")  # margin cross-refs like "23 of 1959."
_INTRA_CHAPTER_PART = re.compile(r"^PART [IVX]+\s*[.\N{EM DASH}\N{EN DASH}-]")


@dataclass(frozen=True)
class TextLine:
    x0: float
    y0: float
    x1: float
    text: str


# A page is a list of PyMuPDF text blocks; a block is a list of lines. Blocks only
# mark paragraph breaks: margin notes can be merged into a main-text block, so
# every line is classified on its own position.
Page = Sequence[Sequence[TextLine]]


def _is_margin(line: TextLine) -> bool:
    return line.x1 < MAIN_COLUMN_LEFT or line.x0 > MAIN_COLUMN_RIGHT


def _margin_notes(page: Page) -> list[tuple[float, str]]:
    """Group margin lines into notes; returns (y of first line, heading text)."""
    margin = sorted(
        (line for block in page for line in block if _is_margin(line)),
        key=lambda line: (line.x0 > MAIN_COLUMN_RIGHT, line.y0),
    )
    groups: list[list[TextLine]] = []
    for line in margin:
        prev = groups[-1][-1] if groups else None
        same_side = prev is not None and (prev.x0 > MAIN_COLUMN_RIGHT) == (
            line.x0 > MAIN_COLUMN_RIGHT
        )
        if prev is not None and same_side and line.y0 - prev.y0 <= MARGIN_LINE_GAP:
            groups[-1].append(line)
        else:
            groups.append([line])
    notes = []
    for group in groups:
        heading = _margin_heading([line.text for line in group])
        if heading is not None:
            notes.append((group[0].y0, heading))
    return notes


def _margin_heading(lines: Sequence[str]) -> str | None:
    """One heading line from a margin note, or None for cross-references."""
    text = ""
    for raw in (line.strip() for line in lines):
        if not raw:
            continue
        if text.endswith("-") and raw[:1].islower():
            text = text[:-1] + raw  # soft hyphen from margin wrapping: "manage-" + "rial"
        else:
            text = f"{text} {raw}".strip()
    if not text or _ACT_REFERENCE.match(text) or not re.search(r"[A-Za-z]{3}", text):
        return None
    return text if text.endswith(".") else f"{text}."


def page_lines(page: Page) -> list[str]:
    """Main-column lines of one page, with section headings placed before their sections."""
    notes = _margin_notes(page)
    lines: list[str] = []
    for block in page:
        for line in block:
            if _is_margin(line) or line.y0 < HEADER_MAX_Y:
                continue
            if _SECTION_START.match(line.text):
                near = [h for y, h in notes if abs(y - line.y0) <= HEADING_Y_TOLERANCE]
                if near:
                    lines += ["", near[0]]
            lines.append(line.text)
        lines.append("")
    return lines


def document_lines(pages: Iterable[Page]) -> list[str]:
    raw = "\n".join("\n".join(page_lines(page)) for page in pages)
    return [line for line in normalize_lines(raw) if not _INTRA_CHAPTER_PART.match(line)]


def _schedule_heading(roman: str | None) -> Callable[[str], bool]:
    """Matcher for 'SCHEDULE IV' (or any schedule heading when roman is None)."""
    pattern = re.compile(rf"^SCHEDULE\s+{roman or '[IVX]+'}$")
    return lambda line: pattern.match(line) is not None


def companies_act_doc() -> SourceDoc:
    return SourceDoc(
        source=RegulationSource.COMPANIES_ACT_2013,
        short_name="Companies Act 2013",
        unit_label="Section",
        id_prefix="ca",
        key_prefix="s",
        source_url=SOURCE_URL,
        as_of=AS_ENACTED,
    )


def build_companies_act_chunks(pages: Iterable[Page], tags: TagMap) -> list[RegulationChunk]:
    doc = companies_act_doc()
    lines = document_lines(pages)
    body = lines[: next(i for i, line in enumerate(lines) if re.match(r"^SCHEDULE\s+I$", line))]
    chunks = unit_chunks(parse_units(body), doc, tags, only=set(SECTIONS))

    for roman in SCHEDULES:
        block = slice_between(lines, _schedule_heading(roman), _schedule_heading(None))
        chunks += schedule_chunks(block, roman, doc, tags)
    return [c.model_copy(update={"notes": PRE_AMENDMENT_NOTE}) for c in chunks]
