import pytest

from app.parsing.agenda import (
    find_agenda_end,
    find_notice_start,
    resolution_kind,
    split_items,
)
from app.parsing.models import BusinessSection


def lines(text: str) -> list[str]:
    return text.strip("\n").splitlines()


def numbers(text: str) -> list[int]:
    return [item.item_no for item in split_items(lines(text))]


def test_bare_numbers_on_their_own_line_with_sections() -> None:
    items = split_items(
        lines("""
ORDINARY BUSINESS
1.
To adopt the financial statements.
2.
To declare a dividend.
SPECIAL BUSINESS
3.
To appoint Mr. A as an Independent Director.
""")
    )

    assert [i.item_no for i in items] == [1, 2, 3]
    assert [i.section for i in items] == [
        BusinessSection.ORDINARY,
        BusinessSection.ORDINARY,
        BusinessSection.SPECIAL,
    ]
    assert items[2].text == "To appoint Mr. A as an Independent Director."


def test_explicit_item_headings_may_repeat_a_number() -> None:
    text = """
1. To adopt the accounts.
2. To declare dividend.
3. To re-appoint Mr. B who retires by rotation.
SPECIAL BUSINESS
Item No.3:
To appoint Mr. C as director.
Item No.4:
To issue bonus shares.
"""
    assert numbers(text) == [1, 2, 3, 3, 4]


def test_numbers_that_skip_ahead_or_go_back_are_text() -> None:
    text = """
1. To adopt the accounts.
6. To carry on business as consultants (an object clause).
2. To declare dividend.
1. a numbered note inside item 2
"""
    assert numbers(text) == [1, 2]


def test_inner_list_continuing_into_next_number_is_not_an_item() -> None:
    text = """
1. To adopt the accounts.
2. To approve the following powers:
1. To borrow money;
2. To invest funds;
3. To open bank accounts;
3. To appoint Mr. D as director.
"""
    # "3. To open bank accounts" continues the inner list (1, 2) of item 2.
    # The real item 3 then looks like the inner list's next entry too, and
    # nothing closes item 2's resolution, so it is absorbed: a known limit.
    assert numbers(text) == [1, 2]


def test_closing_quote_ends_the_inner_list() -> None:
    text = """
1. To adopt the accounts.
2. To approve the following powers:
\N{LEFT DOUBLE QUOTATION MARK}RESOLVED THAT the Board may:
1. borrow money;
2. invest funds.\N{RIGHT DOUBLE QUOTATION MARK}
3. To appoint Mr. D as director.
"""
    assert numbers(text) == [1, 2, 3]


def test_explicit_item_format_rejects_bare_numbers_afterwards() -> None:
    text = """
ITEM NO. 1: ISSUE OF EQUITY SHARES ON A PREFERENTIAL BASIS
RESOLVED THAT shares be allotted to:
Sr. Name
2.
Allottee B
"""
    assert numbers(text) == [1]


def test_summary_table_is_replaced_by_full_agenda_and_vets_later_items() -> None:
    text = """
1.
To adopt the audited financial statements of the company for the year
Ordinary
2.
To reappoint Mr. Kalra as an Executive Director of the company
Special
Ordinary Businesses
1.
To adopt the audited financial statements of the company for the year
RESOLVED THAT the powers of the board include:
2.
To raise or borrow money from banks from time to time
3.
To invest the funds of the company
2.
To reappoint Mr. Kalra as an Executive Director of the company
"""
    items = split_items(lines(text))

    assert [i.item_no for i in items] == [1, 2]
    assert "Kalra" in items[1].text
    assert "raise or borrow" in items[0].text  # stayed inside item 1


def test_find_notice_start_and_agenda_end() -> None:
    doc = lines("""
Dear Sir, please find enclosed the notice.
NOTICE is hereby given that the 10th Annual General Meeting will be held
1. To adopt the accounts.
NOTES:
1. A member may appoint a proxy.
""")
    start = find_notice_start(doc)
    end = find_agenda_end(doc, start)

    assert doc[start].startswith("NOTICE is hereby given")
    assert doc[end] == "NOTES:"


def test_prose_mention_of_statement_does_not_end_agenda() -> None:
    doc = lines("""
Notice is hereby given that the AGM will be held
1. To adopt the accounts.
Explanatory Statement annexed to this Notice, including the details
2. To declare dividend.
EXPLANATORY STATEMENT PURSUANT TO SECTION 102
""")
    assert find_agenda_end(doc, 0) == 4


def test_missing_notice_start_raises() -> None:
    with pytest.raises(ValueError):
        find_notice_start(["Annual report 2025", "Directors' report"])


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("to pass the following resolution as a Special Resolution:", BusinessSection.SPECIAL),
        ("to pass the following resolution as an Ordinary Resolution", BusinessSection.ORDINARY),
        ("to pass the following resolution as Ordinary Resolution", BusinessSection.ORDINARY),
        ("To appoint a director in place of Mr. X", None),
    ],
)
def test_resolution_kind_hint(text: str, kind: BusinessSection | None) -> None:
    assert resolution_kind(text) is kind
