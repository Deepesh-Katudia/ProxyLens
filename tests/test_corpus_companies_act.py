from app.corpus.companies_act import (
    PRE_AMENDMENT_NOTE,
    TextLine,
    build_companies_act_chunks,
    document_lines,
    page_lines,
)
from app.corpus.tagging import TagMap
from app.schemas.regulation import RegulationSource
from app.schemas.resolution import ResolutionType as T

MAIN_X0, MAIN_X1 = 116.5, 476.6
LEFT_MARGIN = (58.5, 105.0)
RIGHT_MARGIN = (488.5, 535.0)


def main(y: float, text: str, indent: float = 0) -> TextLine:
    return TextLine(MAIN_X0 + indent, y, MAIN_X1, text)


def margin(y: float, text: str, side: tuple[float, float] = LEFT_MARGIN) -> TextLine:
    return TextLine(side[0], y, side[1], text)


HEADER = [
    TextLine(117.5, 66.5, 127.3, "82"),
    TextLine(199.6, 66.5, 395.5, "THE  GAZETTE  OF  INDIA  EXTRAORDINARY"),
]


def test_margin_heading_is_placed_before_section_start_mid_block() -> None:
    # Like page 82: chapter title and the section start share one block.
    page = [
        HEADER,
        [
            main(120, "CHAPTER X"),
            main(134, "AUDIT AND AUDITORS"),
            main(148, "139. (1) Every company shall appoint an auditor.", indent=24),
            margin(149, "Appointment"),
            margin(159, "of auditors."),
        ],
    ]

    assert page_lines(page) == [
        "",  # end of the (skipped) running-header block
        "CHAPTER X",
        "AUDIT AND AUDITORS",
        "",
        "Appointment of auditors.",
        "139. (1) Every company shall appoint an auditor.",
        "",
    ]


def test_margin_lines_merged_into_main_block_are_removed() -> None:
    # Like page 93: the right-margin heading came back inside the main block.
    page = [
        [
            margin(97, "Appointment", RIGHT_MARGIN),
            margin(107, "of directors.", RIGHT_MARGIN),
            main(98, "152. (1) Where no provision is made in the articles.", indent=24),
        ]
    ]

    assert page_lines(page)[:3] == [
        "",
        "Appointment of directors.",
        "152. (1) Where no provision is made in the articles.",
    ]


def test_soft_hyphens_in_margin_headings_are_mended() -> None:
    page = [
        [
            main(
                100, "197. (1) The total managerial remuneration shall not exceed 11%.", indent=24
            ),
            margin(100, "Overall manage-"),
            margin(110, "rial remunera-"),
            margin(120, "tion."),
        ]
    ]

    assert "Overall managerial remuneration." in page_lines(page)


def test_act_cross_references_in_margin_are_not_headings() -> None:
    page = [
        [main(100, "148. (1) Cost records.", indent=24), margin(101, "23 of 1959.", RIGHT_MARGIN)]
    ]

    assert page_lines(page) == ["148. (1) Cost records.", ""]


def test_document_lines_drop_intra_chapter_part_titles() -> None:
    pages = [
        [
            [
                main(100, "PART I.\N{EM DASH}Public offer"),
                main(112, "23. (1) A public company may issue securities."),
            ]
        ]
    ]

    assert "PART I.\N{EM DASH}Public offer" not in document_lines(pages)


def test_build_selects_sections_and_flags_pre_amendment_text() -> None:
    tags = TagMap(
        {RegulationSource.COMPANIES_ACT_2013: {"s149": (T.INDEPENDENT_DIRECTOR_APPOINT,)}}
    )
    body = [
        [
            main(
                100,
                "148. (1) The Central Government may direct an audit of cost records.",
                indent=24,
            ),
            margin(100, "Cost audit."),
        ],
        [
            main(
                120,
                "149. (1) Every company shall have a Board of Directors of individuals.",
                indent=24,
            ),
            margin(120, "Company to have Board."),
        ],
        [
            main(
                140,
                "(2) An independent director shall hold office for up to five years.",
                indent=24,
            )
        ],
    ]
    schedules = [
        [main(100, "SCHEDULE I")],
        [
            main(100, "SCHEDULE IV"),
            main(112, "CODE FOR INDEPENDENT DIRECTORS"),
            main(124, "An independent director shall uphold ethical standards of integrity."),
        ],
        [
            main(100, "SCHEDULE V"),
            main(112, "PART I"),
            main(124, "APPOINTMENTS"),
            main(136, "No person shall be eligible for appointment unless conditions are met."),
        ],
        [main(100, "SCHEDULE VI")],
    ]

    chunks = build_companies_act_chunks([body, schedules], tags)
    by_id = {c.id: c for c in chunks}

    assert {"ca_s148_1", "ca_s149_1", "ca_s149_2", "ca_sch4", "ca_sch5_parti"} <= by_id.keys()
    assert by_id["ca_s149_2"].heading == "Company to have Board"
    assert by_id["ca_s149_2"].citation == "Section 149(2), Companies Act 2013"
    assert by_id["ca_s149_2"].applies_to == [T.INDEPENDENT_DIRECTOR_APPOINT]
    assert by_id["ca_sch5_parti"].heading == "APPOINTMENTS"
    assert all(c.notes == PRE_AMENDMENT_NOTE and c.as_of == "2013-08-29" for c in chunks)
