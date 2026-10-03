"""Find the agenda in a notice and split it into numbered items."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.parsing.models import BusinessSection

_NOTICE_START = re.compile(r"hereby\s+given", re.IGNORECASE)
_AGENDA_END = re.compile(
    r"^\s*((?i:notes?)\s*[:.]?\s*$|(?i:notes?)\s*:|(?i:by\s+order\s+of\s+the\s+board)|"
    # The statement heading only in capitals: "Explanatory Statement annexed
    # to this Notice ..." also starts lines in the agenda's notes.
    r"EXPLANATORY\s*(STATEMENT)?\s*$|EXPLANATORY\s+STATEMENT\b)"
)
_SECTION_HEADER = re.compile(r"^\s*(ORDINARY|SPECIAL)\s+BUSINESS(ES)?\b", re.IGNORECASE)
# "Item No. 3:", "ITEM NO.3 TITLE" (explicit, always an item start).
_STRONG_ITEM = re.compile(r"^\s*ITEM\s+NO\.?\s*(\d{1,2})\b\s*[:.\-\N{EN DASH}]?\s*(.*)$", re.I)
# "3." / "3)" at line start (accepted only when it continues the numbering).
_WEAK_ITEM = re.compile(r"^\s*(\d{1,2})\s*[.)](?!\d)\s*(.*)$")
_CLOSING_QUOTES = ("\N{RIGHT DOUBLE QUOTATION MARK}", '"', "\N{RIGHT SINGLE QUOTATION MARK}")
_SPECIAL_HINT = re.compile(r"as\s+(an?\s+)?special\s+resolution", re.IGNORECASE)
_ORDINARY_HINT = re.compile(r"as\s+(an?\s+)?ordinary\s+resolution", re.IGNORECASE)

# A restarted numbering replaces an earlier run (e.g. a summary table of the
# agenda) only if its first item reads like the earlier first item.
RESTART_SIMILARITY = 0.6
SIMILARITY_WORDS = 25
LOOKAHEAD_LINES = 4
_STOPWORDS = frozenset(
    {"the", "and", "for", "from", "with", "that", "this", "company", "any", "such", "its"}
)
MIN_INNER_LIST = 2
INNER_LIST_SLACK = 2


@dataclass
class RawItem:
    item_no: int
    section: BusinessSection | None
    lines: list[str]
    explicit: bool = False  # numbered "Item No. N" rather than a bare "N."

    @property
    def text(self) -> str:
        return "\n".join(line.strip() for line in self.lines if line.strip())


def find_notice_start(lines: Sequence[str]) -> int:
    for i, line in enumerate(lines):
        if _NOTICE_START.search(line):
            return i
    raise ValueError("no 'notice is hereby given' found; is this an AGM/EGM notice?")


def find_agenda_end(lines: Sequence[str], start: int) -> int:
    for i in range(start + 1, len(lines)):
        if _AGENDA_END.match(lines[i]):
            return i
    return len(lines)


def _inner_list(lines: Sequence[str]) -> list[int]:
    """'N.' numbers at line start inside an item's own text."""
    return [int(m.group(1)) for line in lines if (m := _WEAK_ITEM.match(line))]


def _closes_resolution(lines: Sequence[str]) -> bool:
    """True if the item's last non-empty line ends a quoted resolution."""
    last = next((line.strip() for line in reversed(lines) if line.strip()), "")
    return last.endswith(_CLOSING_QUOTES) or last.rstrip(".").endswith(_CLOSING_QUOTES)


def _words(text: str) -> set[str]:
    words = [w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _STOPWORDS]
    return set(words[:SIMILARITY_WORDS])


def _similar(a: str, b: str) -> bool:
    """Overlap coefficient: a short summary entry vs. the start of a full item."""
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= RESTART_SIMILARITY


def _item_start(line: str) -> tuple[int, str, bool] | None:
    """(item number, rest of line, is_strong) if `line` can start an item."""
    if strong := _STRONG_ITEM.match(line):
        return int(strong.group(1)), strong.group(2), True
    if weak := _WEAK_ITEM.match(line):
        return int(weak.group(1)), weak.group(2), False
    return None


def _lookahead(lines: Sequence[str], i: int, rest: str) -> str:
    """Text of a candidate item: rest of its line plus following lines, up to the
    next numbered line."""
    following: list[str] = []
    for line in lines[i + 1 : i + 1 + LOOKAHEAD_LINES]:
        if _item_start(line) is not None:
            break
        following.append(line)
    return " ".join([rest, *following])


def split_items(lines: Sequence[str]) -> list[RawItem]:
    """Split agenda lines into items, rejecting numbered lines inside resolutions."""
    items: list[RawItem] = []
    summary: dict[int, str] = {}  # item titles from an agenda summary table, if any
    section: BusinessSection | None = None

    for i, line in enumerate(lines):
        if header := _SECTION_HEADER.match(line):
            section = BusinessSection(header.group(1).upper())
            continue
        start = _item_start(line)
        if start is not None:
            number, rest, strong = start
            new = RawItem(number, section, [rest] if rest else [], explicit=strong)
            preview = _lookahead(lines, i, rest)
            if strong or _continues(number, items, summary.get(number), preview):
                items.append(new)
                continue
            if _restates(number, items, preview):
                # The earlier run was a summary table; keep it to vet later items.
                summary = {item.item_no: item.text for item in items}
                items = [new]
                continue
        if items:
            items[-1].lines.append(line)
    return items


def _continues(
    number: int,
    items: list[RawItem],
    summary_title: str | None,
    preview: str,
) -> bool:
    """A bare 'N.' starts the next item unless it continues a list inside the item.

    Once a notice numbers items as "Item No. N", a bare "N." is never an item
    (it is a clause or table row inside the resolution). An inner list of two or
    more entries claims numbers up to INNER_LIST_SLACK past its last seen entry,
    since PDF extraction sometimes merges an entry's number into the line above.
    When the notice opened with a summary table, the table decides instead.
    """
    if not items:
        return number == 1
    current = items[-1]
    if current.explicit or number != current.item_no + 1:
        return False
    if summary_title is not None:
        return _similar(preview, summary_title)
    inner = _inner_list(current.lines)
    in_inner_list = len(inner) >= MIN_INNER_LIST and number <= max(inner) + INNER_LIST_SLACK
    return not in_inner_list or _closes_resolution(current.lines)


def _restates(number: int, items: list[RawItem], candidate_text: str) -> bool:
    """A new run from 1 that repeats the first item, e.g. after a summary table."""
    return number == 1 and bool(items) and _similar(candidate_text, items[0].text)


def resolution_kind(text: str) -> BusinessSection | None:
    if _SPECIAL_HINT.search(text):
        return BusinessSection.SPECIAL
    if _ORDINARY_HINT.search(text):
        return BusinessSection.ORDINARY
    return None
