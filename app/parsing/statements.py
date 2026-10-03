"""Find the Section 102 explanatory statement and align it to agenda items."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

# Section heading, e.g. "EXPLANATORY STATEMENT PURSUANT TO SECTION 102" or the
# mixed-case "Explanatory Statement — Pursuant to Section 102 ...". The mixed-case
# form needs a dash or colon: notes often say "Explanatory Statement pursuant to
# Section 102 of the Act ... is annexed", which is prose, not the heading.
_SECTION_START = re.compile(
    r"^\s*(EXPLANATORY(\s+STATEMENT)?\s*$|EXPLANATORY\s+STATEMENT\b|"
    r"STATEMENT\s+PURSUANT\s+TO\s+SECTION\s+102|"
    r"Explanatory\s+Statement\s*[\N{EM DASH}\N{EN DASH}:-])",
)
# Where statements stop: annexures, director profiles, notes, the annual report.
_SECTION_STOP = re.compile(
    r"^\s*(NOTES?\s*[:.]?\s*$|ANNEXURE\b|Annexure\s+(to|[A-Z0-9])\b|"
    r"DETAILS\s+OF\s+(THE\s+)?DIRECTORS?\s+SEEKING|"
    r"Details\s+of\s+(the\s+)?Directors?\s+seeking|"
    r"(BOARD|DIRECTORS)['\N{RIGHT SINGLE QUOTATION MARK}]?S?\s+REPORT|INSTRUCTIONS\s+FOR|"
    r"ROUTE\s+MAP)",
)
_HEADING = re.compile(
    r"^\s*ITEM\s+NOS?\.?\s*(\d[\d\s,&\-\N{EN DASH}]*(?:\s*(?:and|to)\s*\d+)*)(.*)$", re.I
)
# "Item No. 4 of the Notice." is a reference inside a statement, not a heading.
_REFERENCE_TAIL = re.compile(
    r"^\s*(of|in|as|above|set\s+out|for|is|are|was|were|has|have)\b", re.IGNORECASE
)
_BY_ORDER = re.compile(r"^\s*by\s+order\s+of\s+the\s+board", re.IGNORECASE)


@dataclass(frozen=True)
class Statement:
    item_nos: tuple[int, ...]  # empty when the section has no item headings
    text: str


def parse_item_numbers(spec: str) -> tuple[int, ...]:
    """'8 & 9' -> (8, 9); '3-4' / '4 to 6' -> ranges; '3, 4 and 5' -> (3, 4, 5)."""
    numbers: list[int] = []
    for part in re.split(r"\s*(?:,|&|\band\b)\s*", spec.strip()):
        bounds = re.split(r"\s*(?:-|\N{EN DASH}|\bto\b)\s*", part)
        values = [int(b) for b in bounds if b.strip().isdigit()]
        if len(values) == 2 and values[0] < values[1]:
            numbers.extend(range(values[0], values[1] + 1))
        else:
            numbers.extend(values)
    return tuple(dict.fromkeys(numbers))


def find_statement_section(lines: Sequence[str], after: int) -> tuple[int, int] | None:
    """(start, end) line indices of the explanatory statement, if present.

    Starts at the section heading or at the first "Item No." heading after the
    agenda, whichever comes first: some notices print statements for a few items
    before the formal heading.
    """
    start = next(
        (
            i
            for i in range(after, len(lines))
            if _SECTION_START.match(lines[i]) or _heading_numbers(lines[i]) is not None
        ),
        None,
    )
    if start is None:
        return None
    for end in range(start + 1, len(lines)):
        if _SECTION_STOP.match(lines[end]) or _BY_ORDER.match(lines[end]):
            return start, end
    return start, len(lines)


def _heading_numbers(line: str) -> tuple[int, ...] | None:
    match = _HEADING.match(line)
    if match is None or _REFERENCE_TAIL.match(match.group(2)):
        return None
    return parse_item_numbers(match.group(1)) or None


def split_statements(lines: Sequence[str]) -> list[Statement]:
    """Split a statement section at its 'Item No(s).' headings."""
    blocks: list[tuple[tuple[int, ...], list[str]]] = [((), [])]
    for line in lines:
        numbers = _heading_numbers(line)
        if numbers is not None:
            blocks.append((numbers, [line]))
        else:
            blocks[-1][1].append(line)
    statements = [
        Statement(nos, "\n".join(s.strip() for s in body if s.strip())) for nos, body in blocks
    ]
    headed = [s for s in statements if s.item_nos]
    # Without headings the whole section is one statement (single-item notices).
    return headed if headed else [s for s in statements if s.text]
