from pathlib import Path

import pytest

from app.corpus.builder import (
    SourceDoc,
    roman_to_int,
    schedule_chunks,
    slice_between,
    unit_chunks,
)
from app.corpus.chunking import pack_paragraphs
from app.corpus.tagging import TagMap, load_tag_map
from app.corpus.units import LegalUnit, SubUnit
from app.schemas.regulation import RegulationSource
from app.schemas.resolution import ResolutionType as T

DOC = SourceDoc(
    source=RegulationSource.SEBI_LODR_2015,
    short_name="SEBI LODR 2015",
    unit_label="Regulation",
    id_prefix="lodr",
    key_prefix="reg",
    source_url="https://example.test/lodr",
    as_of="2026-07-14",
)
TAGS = TagMap(
    {
        RegulationSource.SEBI_LODR_2015: {
            "reg23": (T.RELATED_PARTY_TRANSACTION,),
            "reg17.6": (T.MANAGERIAL_REMUNERATION,),
            "reg17": (T.NON_INDEPENDENT_DIRECTOR_APPOINT,),
            "sch2.partd": (T.ESOP,),
        }
    }
)
LONG = "word " * 200


def _unit(number: str, *subs: tuple[str | None, tuple[str, ...]]) -> LegalUnit:
    return LegalUnit(number, "Heading", "Chapter IV", tuple(SubUnit(lbl, p) for lbl, p in subs))


def test_unit_chunks_build_ids_citations_and_paths() -> None:
    unit = _unit("23", ("4", ("All material related party transactions need approval.",)))

    [chunk] = unit_chunks([unit], DOC, TAGS)

    assert chunk.id == "lodr_reg23_4"
    assert chunk.citation == "Regulation 23(4), SEBI LODR 2015"
    assert chunk.section_path == ["Chapter IV", "Regulation 23", "(4)"]
    assert chunk.applies_to == [T.RELATED_PARTY_TRANSACTION]
    assert chunk.as_of == "2026-07-14"


def test_sub_unit_tag_overrides_unit_tag() -> None:
    unit = _unit(
        "17",
        ("6", ("Fees payable to executive directors who are promoters.",)),
        ("2", ("Board meets four times a year.",)),
    )

    by_id = {c.id: c for c in unit_chunks([unit], DOC, TAGS)}

    assert by_id["lodr_reg17_6"].applies_to == [T.MANAGERIAL_REMUNERATION]
    assert by_id["lodr_reg17_2"].applies_to == [T.NON_INDEPENDENT_DIRECTOR_APPOINT]


def test_long_sub_unit_is_split_with_same_citation() -> None:
    unit = _unit("23", ("2", (LONG, LONG)))

    chunks = unit_chunks([unit], DOC, TAGS)

    assert [c.id for c in chunks] == ["lodr_reg23_2_p1", "lodr_reg23_2_p2"]
    assert {c.citation for c in chunks} == {"Regulation 23(2), SEBI LODR 2015"}


def test_tiny_and_omitted_units_are_dropped() -> None:
    assert unit_chunks([_unit("9", ("1", ("Omitted.",)))], DOC, TAGS) == []


def test_only_filter_selects_units() -> None:
    units = [
        _unit("17", ("1", ("Composition of the board of directors.",))),
        _unit("23", ("1", ("Policy on materiality of transactions.",))),
    ]

    assert [c.id for c in unit_chunks(units, DOC, TAGS, only={"23"})] == ["lodr_reg23_1"]


def test_schedule_chunks_split_by_part_and_join_wrapped_titles() -> None:
    lines = [
        "SCHEDULE II: CORPORATE GOVERNANCE",
        "PART D: ROLE OF COMMITTEES (OTHER THAN",
        "AUDIT COMMITTEE)",
        "The nomination and remuneration committee shall recommend the remuneration policy.",
    ]

    [chunk] = schedule_chunks(lines, "II", DOC, TAGS)

    assert chunk.id == "lodr_sch2_partd"
    assert chunk.citation == "Schedule II, Part D, SEBI LODR 2015"
    assert chunk.heading == "ROLE OF COMMITTEES (OTHER THAN AUDIT COMMITTEE)"
    assert chunk.applies_to == [T.ESOP]


def test_slice_between_returns_inclusive_start() -> None:
    lines = ["a", "SCHEDULE XII: RPT", "body", "U.K. SINHA", "tail"]

    assert slice_between(
        lines, lambda s: s.startswith("SCHEDULE XII"), lambda s: s == "U.K. SINHA"
    ) == [
        "SCHEDULE XII: RPT",
        "body",
    ]


def test_slice_between_raises_without_start() -> None:
    with pytest.raises(ValueError):
        slice_between(["a"], lambda s: s == "x", lambda s: True)


@pytest.mark.parametrize(("roman", "value"), [("II", 2), ("IV", 4), ("IX", 9), ("XII", 12)])
def test_roman_to_int(roman: str, value: int) -> None:
    assert roman_to_int(roman) == value


def test_pack_paragraphs_windows_oversized_paragraph_with_overlap() -> None:
    words = [f"w{i}" for i in range(500)]

    chunks = pack_paragraphs([" ".join(words)], max_words=280, overlap=40)

    assert len(chunks) == 2
    assert chunks[1].split()[0] == "w240"
    assert chunks[1].split()[-1] == "w499"


def test_pack_paragraphs_rejects_bad_overlap() -> None:
    with pytest.raises(ValueError):
        pack_paragraphs(["x"], max_words=10, overlap=10)


def test_repo_tag_config_loads_and_uses_known_types() -> None:
    tags = load_tag_map(Path("config/corpus_tags.yaml"))

    assert tags.lookup(RegulationSource.SEBI_LODR_2015, "reg23.4", "reg23") == [
        T.RELATED_PARTY_TRANSACTION
    ]
    assert tags.lookup(RegulationSource.COMPANIES_ACT_2013, "s180") == [T.BORROWING_LIMITS]
    assert tags.lookup(RegulationSource.SEBI_LODR_2015, "reg999") == []
