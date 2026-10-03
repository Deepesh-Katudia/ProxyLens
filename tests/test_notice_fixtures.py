"""Phase 2 acceptance: segmentation matches hand-counted items on real notices."""

from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.parsing.models import MeetingType, ParsedNotice
from app.parsing.notice import parse_notice_pdf

FIXTURES = Path("tests/fixtures/notices")
MIN_MATCH_RATE = 0.9  # SPEC: >= 9 of 10 notices


def _manifest() -> list[dict[str, Any]]:
    data = yaml.safe_load((FIXTURES / "manifest.yaml").read_text(encoding="utf-8"))
    return list(data["notices"])


@cache
def _parse(file: str) -> ParsedNotice:
    return parse_notice_pdf(FIXTURES / file)


def test_item_counts_match_hand_counts_on_at_least_90_percent() -> None:
    entries = _manifest()
    mismatches = {
        e["file"]: (e["items"], len(_parse(e["file"]).items))
        for e in entries
        if len(_parse(e["file"]).items) != e["items"]
    }

    match_rate = 1 - len(mismatches) / len(entries)
    assert match_rate >= MIN_MATCH_RATE, f"(expected, got) per mismatch: {mismatches}"


@pytest.mark.parametrize("entry", _manifest(), ids=lambda e: e["file"])
def test_meeting_type_is_detected(entry: dict[str, Any]) -> None:
    assert _parse(entry["file"]).meeting_type is MeetingType(entry["meeting_type"])


def test_shared_statement_is_attached_to_both_items() -> None:
    items = {i.item_no: i for i in _parse("itc_2025.pdf").items}

    assert items[8].explanatory_statement is not None
    assert items[8].explanatory_statement == items[9].explanatory_statement
    assert items[8].explanatory_statement.startswith("Item Nos. 8 & 9")
    assert items[1].explanatory_statement is None  # ordinary business: no statement


def test_repeated_item_number_gives_statement_to_special_business_item() -> None:
    items = _parse("mstc_2016.pdf").items

    assert [i.item_no for i in items] == [1, 2, 3, 3, 4, 5]
    assert items[2].explanatory_statement is None  # ordinary item 3: retirement by rotation
    assert "Sunil Barthwal" in (items[3].explanatory_statement or "")


def test_summary_table_and_inner_power_lists_do_not_create_items() -> None:
    items = _parse("persistent_2025.pdf").items

    assert len(items) == 9
    assert "Sandeep Kalra" in items[6].text
    assert "To raise or borrow" not in items[6].text.split("\n", 1)[0]


def test_single_unheaded_statement_goes_to_the_only_item() -> None:
    [item] = _parse("mediassist_egm_2025.pdf").items

    assert item.explanatory_statement is not None
    assert "preferential" in item.explanatory_statement.lower()
