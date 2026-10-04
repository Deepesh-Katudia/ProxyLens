import pytest

from app.parsing.agenda import split_items
from app.parsing.company import guess_company
from scripts.harvest_notices import looks_like_newspaper_ad


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        # The opening sentence wins, whatever its capitalisation.
        (
            [
                "NOTICE is hereby given that the 5th AGM of the members of "
                "MRP Agro Limited will be held"
            ],
            "MRP Agro Limited",
        ),
        (
            [
                "NOTICE IS HEREBY GIVEN THAT THE 44th AGM OF THE MEMBERS OF "
                "MILLENNIUM ONLINE SOLUTIONS (INDIA) LIMITED WILL"
            ],
            "MILLENNIUM ONLINE SOLUTIONS (INDIA) LIMITED",
        ),
        # Fallback: most frequent "... Limited" on the first pages, minus prose and registrars.
        (
            [
                "Thanking you Yours faithfully For Vipul Limited",
                "Vipul Limited",
                "KFin Technologies Limited",
            ],
            "Vipul Limited",
        ),
        (["RESOLVED THAT MSTC Limited issue bonus shares", "MSTC Limited"], "MSTC Limited"),
        (["Nothing here names a company."], ""),
    ],
)
def test_guess_company(pages: list[str], expected: str) -> None:
    assert guess_company(pages) == expected


def test_exchange_names_are_never_the_issuer() -> None:
    pages = [
        "Shareholders of the Company. This certificate shall also be sent to BSE Ltd",
        "Welcast Steels Limited",
    ]

    assert guess_company(pages) == "Welcast Steels Limited"


def test_newspaper_clippings_are_detected() -> None:
    clipping = "MUMBAI | WEDNESDAY, 4 SEPTEMBER 2024 Financial Express NOTICE OF POSTAL BALLOT " * 3
    notice = [
        "NOTICE is hereby given",
        "1. To adopt accounts",
        "EXPLANATORY STATEMENT",
        "Item No. 1",
    ]

    assert looks_like_newspaper_ad([clipping, "Business Standard"])
    assert looks_like_newspaper_ad(
        ["NOTICE is hereby given. 1. To adopt the accounts."]
    )  # 1 page, no statement
    assert not looks_like_newspaper_ad(notice)


def test_roman_numbered_items_ignore_numbered_tables() -> None:
    lines = [
        "SPECIAL BUSINESSES:",
        "I.",
        "ALTERATION IN CLAUSE 8 OF THE ARTICLES OF ASSOCIATION:",
        "II.",
        "ISSUE OF EQUITY SHARES ON PREFERENTIAL BASIS",
        "Sr. Name of allottee",
        "1.",
        "Kamini Jain 2,00,000",
        "2.",
        "Madhu Rathi 6,400",
        "III.",
        "ISSUE OF WARRANTS",
    ]

    assert [i.item_no for i in split_items(lines)] == [1, 2, 3]
