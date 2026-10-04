"""Hard constraints on the reasoner's output, enforced in code (SPEC 6.2).

1. A citation must name a retrieved chunk and quote a span of it; others are
   dropped and confidence is lowered.
2. Any LAW rule that FAILs rules out FOR.
3. Confidence below the floor, or INSUFFICIENT_DATA on any LAW rule, forces
   NEEDS_REVIEW.

The order matters: dropping citations lowers confidence, which can then trigger
rule 3. The result always satisfies all three, whatever the model returned.
"""

from collections.abc import Mapping, Sequence

from app.rules.models import RuleFinding, RuleKind, RuleStatus
from app.schemas.analysis import Citation, Decision, ReasonerOutput, Recommendation

CONFIDENCE_FLOOR = 0.6
CITATION_PENALTY = 0.15  # confidence lost per dropped citation
MIN_QUOTE_CHARS = 12  # an empty or tiny quote is a substring of anything


def _normalise(text: str) -> str:
    """Collapse whitespace so line breaks in the PDF text do not break quotes."""
    return " ".join(text.split())


def is_valid_citation(citation: Citation, chunks: Mapping[str, str]) -> bool:
    text = chunks.get(citation.regulation_id)
    quote = _normalise(citation.quote)
    return text is not None and len(quote) >= MIN_QUOTE_CHARS and quote in _normalise(text)


def _law(findings: Sequence[RuleFinding], status: RuleStatus) -> list[str]:
    return [f.rule_id for f in findings if f.kind == RuleKind.LAW and f.status == status]


def enforce(
    output: ReasonerOutput, findings: Sequence[RuleFinding], chunks: Mapping[str, str]
) -> Decision:
    """`chunks` maps each retrieved regulation id to its full text."""
    recommendation = output.recommendation
    confidence = output.confidence
    adjustments: list[str] = []

    citations = [c for c in output.citations if is_valid_citation(c, chunks)]
    dropped = len(output.citations) - len(citations)
    if dropped:
        confidence = max(0.0, confidence - CITATION_PENALTY * dropped)
        adjustments.append(
            f"Dropped {dropped} citation(s) not found in the retrieved regulations; "
            f"confidence lowered to {confidence:.2f}."
        )

    failed = _law(findings, RuleStatus.FAIL)
    if failed and recommendation == Recommendation.FOR:
        recommendation = Recommendation.AGAINST
        adjustments.append(f"FOR changed to AGAINST: LAW rule(s) failed ({', '.join(failed)}).")

    insufficient = _law(findings, RuleStatus.INSUFFICIENT_DATA)
    if recommendation != Recommendation.NEEDS_REVIEW:
        if insufficient:
            adjustments.append(
                f"{recommendation.value} changed to NEEDS_REVIEW: insufficient data for LAW "
                f"rule(s) {', '.join(insufficient)}."
            )
            recommendation = Recommendation.NEEDS_REVIEW
        elif confidence < CONFIDENCE_FLOOR:
            adjustments.append(
                f"{recommendation.value} changed to NEEDS_REVIEW: confidence {confidence:.2f} "
                f"is below {CONFIDENCE_FLOOR}."
            )
            recommendation = Recommendation.NEEDS_REVIEW

    return Decision(
        recommendation=recommendation,
        confidence=confidence,
        rationale=output.rationale,
        citations=citations,
        adjustments=adjustments,
    )


def needs_review(reason: str, findings: Sequence[RuleFinding]) -> Decision:
    """The decision when there is no usable reasoner output."""
    output = ReasonerOutput(
        recommendation=Recommendation.NEEDS_REVIEW, confidence=0.0, rationale=reason
    )
    return enforce(output, findings, {})
