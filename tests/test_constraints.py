"""SPEC 6.2 hard constraints: checked over every combination of reasoner output,
rule findings and citations, so a violation is impossible rather than unlikely."""

import itertools

import pytest

from app.pipeline.constraints import (
    CONFIDENCE_FLOOR,
    enforce,
    is_valid_citation,
    needs_review,
)
from app.rules.models import RuleFinding, RuleKind, RuleStatus
from app.schemas.analysis import Citation, ReasonerOutput, Recommendation

CHUNK_TEXT = (
    "No listed entity shall appoint a person or continue the directorship of any person as a "
    "non-executive director who has attained the age of seventy five years unless a special "
    "resolution is passed to that effect."
)
CHUNKS = {"lodr_reg17_1a": CHUNK_TEXT, "s149_10": "An independent director shall hold office."}

VALID = Citation(regulation_id="lodr_reg17_1a", quote="unless a special\n  resolution is passed")
UNKNOWN_ID = Citation(regulation_id="made_up", quote="unless a special resolution is passed")
WRONG_QUOTE = Citation(regulation_id="lodr_reg17_1a", quote="shall never appoint anyone at all")
TINY_QUOTE = Citation(regulation_id="lodr_reg17_1a", quote="the")
EMPTY_QUOTE = Citation(regulation_id="s149_10", quote="")

CITATION_SETS = [
    [],
    [VALID],
    [UNKNOWN_ID],
    [WRONG_QUOTE, TINY_QUOTE, EMPTY_QUOTE],
    [VALID, UNKNOWN_ID, WRONG_QUOTE],
]
CONFIDENCES = [0.0, 0.3, CONFIDENCE_FLOOR - 0.01, CONFIDENCE_FLOOR, 0.75, 0.9, 1.0]
LAW_STATUSES = [None, *RuleStatus]
POLICY_STATUSES = [None, RuleStatus.PASS, RuleStatus.FAIL, RuleStatus.INSUFFICIENT_DATA]


def finding(kind: RuleKind, status: RuleStatus, rule_id: str) -> RuleFinding:
    return RuleFinding(rule_id=rule_id, kind=kind, status=status, detail="d", citation="c")


def finding_sets() -> list[list[RuleFinding]]:
    sets = []
    for law_a, law_b, policy in itertools.product(LAW_STATUSES, LAW_STATUSES, POLICY_STATUSES):
        findings = []
        if law_a:
            findings.append(finding(RuleKind.LAW, law_a, "LAW_A"))
        if law_b:
            findings.append(finding(RuleKind.LAW, law_b, "LAW_B"))
        if policy:
            findings.append(finding(RuleKind.POLICY, policy, "POL"))
        sets.append(findings)
    return sets


def test_constraints_hold_for_every_combination() -> None:
    cases = 0
    for recommendation, confidence, citations, findings in itertools.product(
        Recommendation, CONFIDENCES, CITATION_SETS, finding_sets()
    ):
        output = ReasonerOutput(
            recommendation=recommendation,
            confidence=confidence,
            rationale="r",
            citations=citations,
        )
        decision = enforce(output, findings, CHUNKS)
        law = {f.status for f in findings if f.kind == RuleKind.LAW}
        context = (recommendation, confidence, citations, findings, decision)

        if RuleStatus.FAIL in law:
            assert decision.recommendation != Recommendation.FOR, context
        if RuleStatus.INSUFFICIENT_DATA in law or decision.confidence < CONFIDENCE_FLOOR:
            assert decision.recommendation == Recommendation.NEEDS_REVIEW, context
        assert all(is_valid_citation(c, CHUNKS) for c in decision.citations), context
        assert 0.0 <= decision.confidence <= confidence, context
        if decision.recommendation != recommendation or decision.citations != citations:
            assert decision.adjustments, context
        cases += 1
    assert cases > 5000


def test_clean_output_passes_through_unchanged() -> None:
    output = ReasonerOutput(
        recommendation=Recommendation.FOR, confidence=0.8, rationale="ok", citations=[VALID]
    )
    passing = [
        finding(RuleKind.LAW, RuleStatus.PASS, "X"),
        finding(RuleKind.POLICY, RuleStatus.FAIL, "P"),
    ]

    decision = enforce(output, passing, CHUNKS)

    assert decision.model_dump(exclude={"adjustments"}) == output.model_dump()
    assert decision.adjustments == []


def test_dropped_citations_lower_confidence_into_review() -> None:
    output = ReasonerOutput(
        recommendation=Recommendation.AGAINST,
        confidence=0.7,
        rationale="r",
        citations=[UNKNOWN_ID, WRONG_QUOTE],
    )

    decision = enforce(output, [], CHUNKS)

    assert decision.citations == []
    assert decision.confidence == pytest.approx(0.4)
    assert decision.recommendation == Recommendation.NEEDS_REVIEW
    assert len(decision.adjustments) == 2


def test_law_failure_turns_for_into_against() -> None:
    output = ReasonerOutput(recommendation=Recommendation.FOR, confidence=0.9, rationale="r")

    decision = enforce(output, [finding(RuleKind.LAW, RuleStatus.FAIL, "ID_TENURE_MAX")], {})

    assert decision.recommendation == Recommendation.AGAINST
    assert "ID_TENURE_MAX" in decision.adjustments[0]


def test_needs_review_fallback() -> None:
    decision = needs_review("reasoner failed", [])

    assert decision.recommendation == Recommendation.NEEDS_REVIEW
    assert decision.confidence == 0.0 and decision.citations == []
