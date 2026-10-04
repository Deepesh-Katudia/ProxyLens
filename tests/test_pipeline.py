"""End-to-end: a real notice PDF through the LangGraph pipeline with mocked LLMs
and a fake retriever (SPEC 10, Phase 5)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.base import LLMResponse, Message
from app.llm.extraction import EXTRACTION_SCHEMA
from app.pipeline.constraints import CONFIDENCE_FLOOR, is_valid_citation
from app.pipeline.graph import NODE_ORDER, analyse_notice, build_graph
from app.pipeline.nodes import PipelineDeps
from app.pipeline.state import Flag, PipelineState
from app.rules.engine import load_policy
from app.rules.models import RuleKind, RuleStatus
from app.schemas.analysis import ItemAnalysis, Recommendation
from app.schemas.regulation import RegulationHit, RegulationSource
from app.schemas.resolution import ResolutionType
from scripts.smoke_student import parse_user_message

NOTICE = Path("tests/fixtures/notices/itc_2025.pdf")
NOTICE_ITEMS = 11  # hand-counted in tests/fixtures/notices/manifest.yaml
FALLBACK_ITEM = 4  # the student fails on this item; the teacher answers
LAW_FAIL_ITEM = 3  # extracted as an independent director with a 6-year term

HITS = [
    RegulationHit(
        id="s149_10",
        source=RegulationSource.COMPANIES_ACT_2013,
        citation="Section 149(10), Companies Act 2013",
        heading="Term of independent director",
        text="An independent director shall hold office for a term up to five consecutive years "
        "on the Board of a company.",
        applies_to=[ResolutionType.INDEPENDENT_DIRECTOR_APPOINT],
        source_url="https://example.org/ca",
        score=0.9,
    ),
    RegulationHit(
        id="lodr_reg25_2a",
        source=RegulationSource.SEBI_LODR_2015,
        citation="Regulation 25(2A), SEBI LODR 2015",
        heading="Obligations with respect to independent directors",
        text="The appointment, re-appointment or removal of an independent director of a listed "
        "entity, shall be subject to the approval of shareholders by way of a special resolution.",
        applies_to=[ResolutionType.INDEPENDENT_DIRECTOR_APPOINT],
        source_url="https://example.org/lodr",
        score=0.8,
    ),
]


def extraction_for(item_no: int, *, title: str = "Item") -> dict[str, Any]:
    base: dict[str, Any] = {
        "item_no": item_no,
        "title": title,
        "resolution_type": "OTHER",
        "is_special_resolution": False,
        "persons": [],
        "amounts": [],
        "counterparty": None,
        "counterparty_is_related": None,
        "transaction_nature": None,
        "duration_years": None,
        "key_facts": [],
    }
    if item_no == 1:
        base |= {"resolution_type": "ADOPT_FINANCIALS", "title": "Adopt financial statements"}
    elif item_no == 2:
        base |= {"resolution_type": "DIVIDEND", "title": "Declare final dividend"}
    elif item_no == LAW_FAIL_ITEM:
        base |= {
            "resolution_type": "INDEPENDENT_DIRECTOR_APPOINT",
            "title": "Appointment of an Independent Director",
            "persons": [
                {
                    "name": "Ms A",
                    "role": "Independent Director",
                    "age": 58,
                    "din": None,
                    "is_promoter": False,
                    "tenure_years_proposed": 6,
                    "prior_tenure_years": 0,
                    "board_attendance_pct": None,
                }
            ],
        }
    return base


class FakeExtractor:
    """Answers from the item number in the prompt; can be told to fail on some items."""

    def __init__(self, name: str, fail_on: frozenset[int] = frozenset()) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.fail_on = fail_on
        self.items: list[int] = []

    def generate_json(
        self, messages: list[Message], schema: dict[str, Any], schema_name: str
    ) -> LLMResponse:
        assert schema == EXTRACTION_SCHEMA
        item_no, _, _ = parse_user_message(messages[1].content)
        self.items.append(item_no)
        if item_no in self.fail_on:
            return LLMResponse("{not json", self.model, latency_ms=5)
        return LLMResponse(json.dumps(extraction_for(item_no)), self.model, latency_ms=5)


class FakeReasoner:
    """Always says FOR with one real and one invented citation."""

    name = "fake_reasoner"
    model = "fake-reasoner-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(
        self, messages: list[Message], schema: dict[str, Any], schema_name: str
    ) -> LLMResponse:
        self.prompts.append(messages[1].content)
        reply = {
            "recommendation": "FOR",
            "confidence": 0.9,
            "rationale": "Looks routine.",
            "citations": [
                {"regulation_id": "s149_10", "quote": "a term up to five consecutive years"},
                {"regulation_id": "s999", "quote": "this section does not exist anywhere"},
            ],
        }
        return LLMResponse(json.dumps(reply), self.model)


class FakeRetriever:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, ResolutionType | None, int]] = []

    async def __call__(
        self, query: str, resolution_type: ResolutionType | None, k: int
    ) -> list[RegulationHit]:
        self.calls.append((query, resolution_type, k))
        if self.fail:
            raise RuntimeError("Atlas unavailable")
        return HITS


def deps(**overrides: Any) -> PipelineDeps:
    values: dict[str, Any] = {
        "student": FakeExtractor("student", fail_on=frozenset({FALLBACK_ITEM})),
        "teacher": FakeExtractor("teacher"),
        "reasoner": FakeReasoner(),
        "retriever": FakeRetriever(),
        "rules": load_policy(),
    }
    return PipelineDeps(**(values | overrides))


def by_item(analyses: list[ItemAnalysis]) -> dict[int, ItemAnalysis]:
    return {a.item_no: a for a in analyses}


def assert_constraints(analyses: list[ItemAnalysis]) -> None:
    for analysis in analyses:
        law = {f.status for f in analysis.rule_findings if f.kind == RuleKind.LAW}
        if RuleStatus.FAIL in law:
            assert analysis.recommendation != Recommendation.FOR
        if RuleStatus.INSUFFICIENT_DATA in law or analysis.confidence < CONFIDENCE_FLOOR:
            assert analysis.recommendation == Recommendation.NEEDS_REVIEW
        chunks = {hit.id: hit.text for hit in HITS if hit.id in analysis.retrieved_ids}
        assert all(is_valid_citation(c, chunks) for c in analysis.citations)


@pytest.fixture(scope="module")
def pdf() -> bytes:
    return NOTICE.read_bytes()


async def test_full_notice_end_to_end(pdf: bytes) -> None:
    pipeline = deps()

    analyses = await analyse_notice(pipeline, pdf)

    assert len(analyses) == NOTICE_ITEMS
    assert [a.seq for a in analyses] == list(range(1, NOTICE_ITEMS + 1))
    assert_constraints(analyses)
    items = by_item(analyses)

    routine = items[1]
    assert routine.resolution_type == ResolutionType.ADOPT_FINANCIALS
    assert routine.recommendation == Recommendation.FOR
    assert [c.regulation_id for c in routine.citations] == ["s149_10"]  # invented one dropped
    assert routine.confidence == pytest.approx(0.75)
    assert routine.retrieved_ids == ["s149_10", "lodr_reg25_2a"]

    breach = items[LAW_FAIL_ITEM]
    failed = [f.rule_id for f in breach.rule_findings if f.status == RuleStatus.FAIL]
    assert "ID_TENURE_MAX" in failed
    assert breach.recommendation == Recommendation.AGAINST
    assert any("FOR changed to AGAINST" in a for a in breach.adjustments)

    fallback = items[FALLBACK_ITEM]
    assert fallback.extractor is not None and fallback.extractor.used_fallback
    assert fallback.extractor.provider == "teacher"
    assert Flag.TEACHER_FALLBACK in fallback.flags
    assert pipeline.teacher is not None
    assert pipeline.teacher.items == [FALLBACK_ITEM]  # type: ignore[attr-defined]


async def test_retrieval_is_filtered_by_type_except_other(pdf: bytes) -> None:
    retriever = FakeRetriever()

    await analyse_notice(deps(retriever=retriever), pdf)

    types = [call[1] for call in retriever.calls]
    assert ResolutionType.ADOPT_FINANCIALS in types
    assert None in types  # OTHER items search without a type filter
    assert ResolutionType.OTHER not in types
    assert all(call[2] == 6 for call in retriever.calls)


async def test_without_a_reasoner_everything_needs_review(pdf: bytes) -> None:
    analyses = await analyse_notice(deps(reasoner=None), pdf)

    assert {a.recommendation for a in analyses} == {Recommendation.NEEDS_REVIEW}
    assert_constraints(analyses)


async def test_failures_degrade_to_flags_not_errors(pdf: bytes) -> None:
    pipeline = deps(
        student=FakeExtractor("student", fail_on=frozenset({1})),
        teacher=None,
        retriever=FakeRetriever(fail=True),
    )

    analyses = await analyse_notice(pipeline, pdf)

    items = by_item(analyses)
    assert Flag.EXTRACTION_FAILED in items[1].flags
    assert items[1].recommendation == Recommendation.NEEDS_REVIEW and items[1].extraction is None
    assert all(Flag.RETRIEVAL_FAILED in items[n].flags for n in (2, 3))
    assert items[2].citations == []  # nothing retrieved, so every citation is dropped
    assert_constraints(analyses)


def test_graph_has_the_spec_node_order() -> None:
    graph = build_graph(deps())

    assert NODE_ORDER == (
        "parse",
        "extract",
        "validate",
        "retrieve",
        "rule_check",
        "reason",
        "assemble",
    )
    assert set(NODE_ORDER) <= set(graph.get_graph().nodes)


async def test_validate_trusts_the_notice_over_the_model(pdf: bytes) -> None:
    graph = build_graph(deps())
    state = await graph.ainvoke(PipelineState(pdf=pdf))

    for item in state["items"]:
        if item.extraction is not None:
            assert item.extraction.item_no == item.item_no
            if item.kind_hint is not None:
                assert item.extraction.is_special_resolution == (item.kind_hint.value == "SPECIAL")
