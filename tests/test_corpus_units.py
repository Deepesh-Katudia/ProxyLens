import pytest

from app.corpus.units import number_key, parse_units, to_paragraphs

LODR_LIKE = """CHAPTER IV
OBLIGATIONS

Board of Directors.
17.
(1) The composition of board of directors shall be as follows:
(a) at least one woman director;
Provided that the top 1000 listed entities shall have an independent woman director.
(1A) No listed entity shall appoint a non-executive director aged seventy five.
(2) The board shall meet at least four times a year.

Maximum number of directorships.
17A. A person shall not be a director in more than seven listed entities.

Related party transactions.
23.
(1) The listed entity shall formulate a policy on materiality.
(4) All material related party transactions shall require prior approval.
The amount referred to in clause (1) of regulation 2 applies.

Dividend Distribution Policy.
24A (1) The top 1000 listed entities shall formulate a policy.
""".splitlines()


@pytest.fixture
def units() -> dict[str, object]:
    return {u.number: u for u in parse_units(LODR_LIKE)}


def test_parses_units_in_order_with_headings() -> None:
    parsed = parse_units(LODR_LIKE)

    assert [u.number for u in parsed] == ["17", "17A", "23", "24A"]
    assert [u.heading for u in parsed] == [
        "Board of Directors",
        "Maximum number of directorships",
        "Related party transactions",
        "Dividend Distribution Policy",
    ]
    assert all(u.chapter == "Chapter IV" for u in parsed)


def test_splits_sub_units_and_keeps_provisos_as_paragraphs() -> None:
    reg17 = parse_units(LODR_LIKE)[0]

    assert [s.label for s in reg17.subunits] == ["1", "1A", "2"]
    assert reg17.subunits[0].paragraphs == (
        "The composition of board of directors shall be as follows:",
        "(a) at least one woman director;",
        "Provided that the top 1000 listed entities shall have an independent woman director.",
    )


def test_heading_of_next_unit_is_not_left_in_previous_unit() -> None:
    reg17 = parse_units(LODR_LIKE)[0]

    assert "Maximum number of directorships." not in " ".join(reg17.subunits[-1].paragraphs)


def test_unit_without_sub_units_keeps_text_under_none_label() -> None:
    reg17a = parse_units(LODR_LIKE)[1]

    assert [s.label for s in reg17a.subunits] == [None]


def test_cross_reference_lines_do_not_start_units_or_sub_units() -> None:
    reg23 = parse_units(LODR_LIKE)[2]

    # "(1) of regulation 2" inside 23(4) must not restart the sub-unit sequence.
    assert [s.label for s in reg23.subunits] == ["1", "4"]


def test_unit_number_without_period_is_accepted_before_sub_unit_one() -> None:
    reg43a = parse_units(LODR_LIKE)[3]

    assert reg43a.number == "24A"
    assert [s.label for s in reg43a.subunits] == ["1"]


def test_backwards_numbers_are_treated_as_text() -> None:
    lines = ["5. First unit.", "3. Not a new unit, a list item.", "6. Second unit."]

    assert [u.number for u in parse_units(lines)] == ["5", "6"]


def test_number_key_orders_suffixes() -> None:
    assert sorted(["17A", "17", "18", "1B", "1A"], key=number_key) == [
        "1A",
        "1B",
        "17",
        "17A",
        "18",
    ]


def test_to_paragraphs_splits_on_blank_lines() -> None:
    assert to_paragraphs(["first line", "continues", "", "second"]) == (
        "first line continues",
        "second",
    )
