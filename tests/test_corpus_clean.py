from app.corpus.clean import clean_pages, join_lines, remove_amendment_markers, strip_page

SEPARATOR = " " * 58


def test_strip_page_drops_page_number_and_footnotes() -> None:
    page = "\n".join([" ", "40 ", " ", "(2) Body text.", SEPARATOR, "206 Substituted by ..."])

    assert strip_page(page) == " \n(2) Body text."


def test_strip_page_keeps_pages_without_footnotes() -> None:
    assert strip_page("12\nSome text") == "Some text"


def test_remove_markers_keeps_operative_words() -> None:
    raw = "the 133[persons identified] and 134[Provided that x];"

    assert remove_amendment_markers(raw) == "the persons identified and Provided that x;"


def test_remove_markers_drops_omissions_and_trailing_numbers() -> None:
    raw = "top 135[***] entities [with effect from July 01, 2019]210 a transaction"

    assert (
        remove_amendment_markers(raw)
        == "top  entities with effect from July 01, 2019 a transaction"
    )


def test_remove_markers_handles_braces() -> None:
    assert remove_amendment_markers("exceed 211{five} percent") == "exceed five percent"


def test_remove_markers_keeps_parenthesised_numbers() -> None:
    assert remove_amendment_markers("sub-regulation (2) of regulation 15") == (
        "sub-regulation (2) of regulation 15"
    )


def test_clean_pages_normalizes_spacing() -> None:
    lines = clean_pages(["1\nresolution plan being approved 227[:]]228  ", "2\n  next   page"])

    assert lines == ["resolution plan being approved:", "next page"]


def test_join_lines_mends_hyphenated_words() -> None:
    assert join_lines(["executive and non-", "executive directors", "", "of the board"]) == (
        "executive and non-executive directors of the board"
    )
