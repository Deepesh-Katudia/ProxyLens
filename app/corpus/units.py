"""Split cleaned legal text into numbered units: regulation/section -> sub-unit.

Both SEBI regulations and the Companies Act number their top-level units
``23.`` / ``17A.`` and their sub-units ``(1)`` / ``(1A)``. Numbers are only
accepted when they advance the sequence by a small step, which filters out
list items and cross-references that happen to start a line.
"""

import re
from dataclasses import dataclass, field

from app.corpus.clean import join_lines

# "23. (1) ..." and, occasionally in consolidated texts, "43A (1) ..." without the period.
_UNIT_START = re.compile(r"^(\d{1,3}[A-Z]{0,3})(?:\.\s*|\s+(?=\(1\)))(.*)$")
_SUB_START = re.compile(r"^\((\d{1,2}[A-Z]{0,3})\)\.?\s*(.*)$")
_CHAPTER = re.compile(r"^CHAPTER ([IVXL]+[A-Z]?)$")
# A clause, proviso or explanation that should start its own paragraph.
_PARAGRAPH_START = re.compile(
    r"^(Provided|Explanation|Illustration|\([a-z]{1,2}\)|\([ivx]{1,5}\)|[a-z]\))"
)

MAX_HEADING_CHARS = 120
MAX_UNIT_STEP = 6
MAX_SUB_STEP = 3


@dataclass(frozen=True)
class SubUnit:
    label: str | None  # "4", "1A", or None for text before the first sub-unit
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class LegalUnit:
    number: str
    heading: str
    chapter: str | None
    subunits: tuple[SubUnit, ...]


def number_key(label: str) -> tuple[int, str]:
    """Sort key for labels like '17', '17A', '1B'."""
    digits = re.match(r"\d+", label)
    if digits is None:
        raise ValueError(f"not a numbered label: {label!r}")
    return int(digits.group()), label[digits.end() :]


def _advances(prev: str | None, label: str, max_step: int) -> bool:
    new = number_key(label)
    if prev is None:
        return True
    old = number_key(prev)
    return new > old and new[0] - old[0] <= max_step


def _is_heading(lines: list[str], idx: int) -> bool:
    """A short line ending in '.', with a blank line (or nothing) above it."""
    line = lines[idx]
    if not line or len(line) > MAX_HEADING_CHARS or not line.endswith("."):
        return False
    return idx == 0 or not lines[idx - 1]


def to_paragraphs(lines: list[str]) -> tuple[str, ...]:
    """Group lines into paragraphs at blank lines and clause/proviso starts."""
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        starts_new = not line or bool(_PARAGRAPH_START.match(line))
        if starts_new and current:
            paragraphs.append(join_lines(current))
            current = []
        if line:
            current.append(line)
    if current:
        paragraphs.append(join_lines(current))
    return tuple(p for p in paragraphs if p)


@dataclass
class _UnitBuilder:
    number: str
    heading: str
    chapter: str | None
    subs: list[tuple[str | None, list[str]]] = field(default_factory=list)

    def add_line(self, line: str) -> None:
        if not self.subs:
            self.subs.append((None, []))
        self.subs[-1][1].append(line)

    def start_sub(self, label: str, first_line: str) -> None:
        self.subs.append((label, [first_line] if first_line else []))

    @property
    def last_sub_label(self) -> str | None:
        labels = [label for label, _ in self.subs if label is not None]
        return labels[-1] if labels else None

    def build(self) -> LegalUnit:
        subunits = tuple(
            SubUnit(label, paras) for label, lines in self.subs if (paras := to_paragraphs(lines))
        )
        return LegalUnit(self.number, self.heading, self.chapter, subunits)


def parse_units(lines: list[str]) -> list[LegalUnit]:
    """Parse cleaned lines into numbered legal units with sub-units."""
    units: list[LegalUnit] = []
    current: _UnitBuilder | None = None
    chapter: str | None = None

    for idx, line in enumerate(lines):
        if chapter_match := _CHAPTER.match(line):
            chapter = f"Chapter {chapter_match.group(1)}"
            continue

        unit_match = _UNIT_START.match(line)
        prev_number = current.number if current else None
        if unit_match and _advances(prev_number, unit_match.group(1), MAX_UNIT_STEP):
            heading = ""
            if idx > 0 and _is_heading(lines, idx - 1):
                heading = lines[idx - 1].rstrip(".")
                if current is not None:
                    _drop_trailing(current, lines[idx - 1])
            if current is not None:
                units.append(current.build())
            current = _UnitBuilder(unit_match.group(1), heading, chapter)
            _feed(current, unit_match.group(2))
            continue

        if current is not None:
            _feed(current, line)

    if current is not None:
        units.append(current.build())
    return units


def _feed(unit: _UnitBuilder, line: str) -> None:
    sub_match = _SUB_START.match(line)
    if sub_match and _advances(unit.last_sub_label, sub_match.group(1), MAX_SUB_STEP):
        unit.start_sub(sub_match.group(1), sub_match.group(2))
    else:
        unit.add_line(line)


def _drop_trailing(unit: _UnitBuilder, heading_line: str) -> None:
    """The next unit's heading was appended to this unit; remove it."""
    if unit.subs and unit.subs[-1][1] and unit.subs[-1][1][-1] == heading_line:
        unit.subs[-1][1].pop()
