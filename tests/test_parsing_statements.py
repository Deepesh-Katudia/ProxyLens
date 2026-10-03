import pytest

from app.parsing.agenda import RawItem
from app.parsing.models import BusinessSection, MeetingType
from app.parsing.notice import align_statements, detect_meeting_type, segment_notice
from app.parsing.pdf_text import strip_running_lines
from app.parsing.statements import (
    Statement,
    find_statement_section,
    parse_item_numbers,
    split_statements,
)

SPECIAL = BusinessSection.SPECIAL
ORDINARY = BusinessSection.ORDINARY


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("6", (6,)),
        ("8 & 9", (8, 9)),
        ("3-4", (3, 4)),
        ("4 to 6", (4, 5, 6)),
        ("3, 4 and 5", (3, 4, 5)),
        ("10 & 11", (10, 11)),
    ],
)
def test_parse_item_numbers(spec: str, expected: tuple[int, ...]) -> None:
    assert parse_item_numbers(spec) == expected


def test_split_statements_skips_in_text_references() -> None:
    section = [
        "EXPLANATORY STATEMENT PURSUANT TO SECTION 102",
        "Item No. 4",
        "The Board recommends the resolution set out at",
        "Item No. 4 of the Notice.",
        "Item Nos. 5 & 6: Related party transactions",
        "Approval is sought for transactions with ABC Ltd.",
    ]

    statements = split_statements(section)

    assert [s.item_nos for s in statements] == [(4,), (5, 6)]
    assert "Item No. 4 of the Notice." in statements[0].text


def test_section_without_item_headings_is_one_statement() -> None:
    section = ["EXPLANATORY STATEMENT", "The Company proposes a preferential issue."]

    [statement] = split_statements(section)

    assert statement.item_nos == ()
    assert "preferential issue" in statement.text


def test_find_section_ignores_prose_and_starts_at_early_item_heading() -> None:
    doc = [
        "NOTES:",
        "1. The Explanatory Statement pursuant to Section 102 of the Act is annexed.",
        "Item No. 5: Re-appointment of Independent Director",
        "Mr. X has served one term.",
        "EXPLANATORY STATEMENT IN RESPECT OF THE SPECIAL BUSINESS",
        "Item No. 6: Amendment to MoA",
        "Annexure A",
    ]

    assert find_statement_section(doc, after=0) == (2, 6)


def test_find_section_returns_none_without_statement() -> None:
    assert find_statement_section(["NOTES:", "1. Proxy forms."], after=0) is None


def _item(no: int, section: BusinessSection | None) -> RawItem:
    return RawItem(no, section, [f"item {no}"])


def test_align_gives_repeated_numbers_to_the_later_item() -> None:
    items = [_item(3, ORDINARY), _item(3, SPECIAL)]

    aligned = align_statements(items, [Statement((3,), "nominee director")])

    assert aligned == {1: "nominee director"}


def test_align_unheaded_statement_to_sole_special_item() -> None:
    items = [_item(1, ORDINARY), _item(2, SPECIAL)]

    assert align_statements(items, [Statement((), "why")]) == {1: "why"}
    assert (
        align_statements(
            [_item(1, ORDINARY), _item(2, SPECIAL), _item(3, SPECIAL)], [Statement((), "x")]
        )
        == {}
    )


@pytest.mark.parametrize(
    ("text", "meeting_type"),
    [
        ("the 10th Annual General Meeting of the Members", MeetingType.AGM),
        ("an Extra-ordinary General Meeting (EGM) of the Members", MeetingType.EGM),
        ("proposed for approval by the members by way of Postal Ballot", MeetingType.POSTAL_BALLOT),
        ("a meeting of creditors", MeetingType.UNKNOWN),
    ],
)
def test_detect_meeting_type(text: str, meeting_type: MeetingType) -> None:
    assert detect_meeting_type(text) is meeting_type


def test_strip_running_lines_keeps_bare_numbers_and_drops_headers() -> None:
    bodies = ["Adopt accounts", "Declare dividend", "Appoint auditor", "Approve borrowing"]
    pages = [
        f"NOTICE OF 114TH ANNUAL GENERAL MEETING\n{n}.\n{body}\n{n}"
        for n, body in enumerate(bodies, start=1)
    ]

    cleaned = strip_running_lines(pages)

    assert all("NOTICE OF" not in page for page in cleaned)
    assert cleaned[0].splitlines() == ["1.", "Adopt accounts"]  # page number "1" dropped


def test_segment_notice_end_to_end() -> None:
    page = "\n".join(
        [
            "NOTICE is hereby given that the 5th Annual General Meeting will be held",
            "ORDINARY BUSINESS",
            "1. To adopt the accounts.",
            "SPECIAL BUSINESS",
            "2. To consider and if thought fit to pass the following as a Special Resolution:",
            "“RESOLVED THAT Ms. Y be appointed.”",
            "By Order of the Board",
            "NOTES:",
            "1. Proxy forms must reach us 48 hours before the meeting.",
            "EXPLANATORY STATEMENT PURSUANT TO SECTION 102",
            "Item No. 2",
            "Ms. Y is a chartered accountant with 20 years of experience.",
        ]
    )

    notice = segment_notice([page])

    assert notice.meeting_type is MeetingType.AGM
    assert [(i.seq, i.item_no, i.section) for i in notice.items] == [
        (1, 1, ORDINARY),
        (2, 2, SPECIAL),
    ]
    assert notice.items[1].resolution_kind_hint is SPECIAL
    assert "chartered accountant" in (notice.items[1].explanatory_statement or "")
    assert notice.items[0].explanatory_statement is None
