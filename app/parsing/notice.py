"""Segment an AGM/EGM/postal-ballot notice into items with explanatory statements."""

import re
from collections.abc import Sequence
from pathlib import Path

from app.parsing.agenda import (
    RawItem,
    find_agenda_end,
    find_notice_start,
    resolution_kind,
    split_items,
)
from app.parsing.models import BusinessSection, MeetingType, NoticeItem, ParsedNotice
from app.parsing.pdf_text import extract_pages, strip_running_lines
from app.parsing.statements import Statement, find_statement_section, split_statements

_MEETING_PATTERNS = (
    (MeetingType.POSTAL_BALLOT, re.compile(r"postal\s+ballot", re.IGNORECASE)),
    (MeetingType.EGM, re.compile(r"extra[\s-]*ordinary\s+general\s+meeting", re.IGNORECASE)),
    (MeetingType.AGM, re.compile(r"annual\s+general\s+meeting", re.IGNORECASE)),
)
MEETING_TYPE_WINDOW = 600  # characters after "hereby given" that name the meeting


def detect_meeting_type(text: str) -> MeetingType:
    for meeting_type, pattern in _MEETING_PATTERNS:
        if pattern.search(text):
            return meeting_type
    return MeetingType.UNKNOWN


def align_statements(items: list[RawItem], statements: list[Statement]) -> dict[int, str]:
    """Map item index -> statement text.

    A statement for "Item Nos. 8 & 9" goes to both items. If an item number
    repeats (special business restarting its numbering), the later item, i.e.
    the special-business one, gets the statement. A section without headings
    belongs to the only special-business item, if there is exactly one.
    """
    by_number: dict[int, int] = {}
    for index, item in enumerate(items):
        by_number[item.item_no] = index  # later items win

    aligned: dict[int, str] = {}
    for statement in statements:
        if not statement.item_nos:
            candidates = [i for i, it in enumerate(items) if it.section is BusinessSection.SPECIAL]
            if len(candidates) != 1 and len(items) == 1:
                candidates = [0]
            if len(candidates) == 1:
                aligned[candidates[0]] = statement.text
            continue
        for number in statement.item_nos:
            if number in by_number:
                aligned[by_number[number]] = statement.text
    return aligned


def segment_notice(pages: Sequence[str]) -> ParsedNotice:
    lines = "\n".join(strip_running_lines(pages)).splitlines()
    start = find_notice_start(lines)
    agenda_end = find_agenda_end(lines, start)
    raw_items = split_items(lines[start + 1 : agenda_end])

    section = find_statement_section(lines, agenda_end)
    statements = split_statements(lines[section[0] : section[1]]) if section else []
    aligned = align_statements(raw_items, statements)

    preamble = " ".join(lines[start : start + 12])[:MEETING_TYPE_WINDOW]
    items = [
        NoticeItem(
            seq=index + 1,
            item_no=raw.item_no,
            section=raw.section,
            text=raw.text,
            explanatory_statement=aligned.get(index),
            resolution_kind_hint=resolution_kind(raw.text),
        )
        for index, raw in enumerate(raw_items)
    ]
    return ParsedNotice(
        meeting_type=detect_meeting_type(preamble),
        page_count=len(pages),
        items=items,
    )


def parse_notice_pdf(source: Path | bytes) -> ParsedNotice:
    return segment_notice(extract_pages(source))
