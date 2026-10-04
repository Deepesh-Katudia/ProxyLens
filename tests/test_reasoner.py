import json
from typing import Any

from app.llm.base import LLMError, LLMResponse, Message
from app.llm.reasoner import REASONER_SCHEMA, build_reasoner_input, reason
from app.rules.engine import load_policy
from app.rules.models import RuleFinding, RuleKind, RuleStatus
from app.schemas.analysis import Recommendation
from app.schemas.regulation import RegulationHit, RegulationSource
from app.schemas.resolution import ResolutionExtraction, ResolutionType

EXTRACTION = ResolutionExtraction(
    item_no=4,
    title="Appointment of Ms A as Independent Director",
    resolution_type=ResolutionType.INDEPENDENT_DIRECTOR_APPOINT,
    is_special_resolution=True,
)
FINDINGS = [
    RuleFinding(
        rule_id="ID_TENURE_MAX",
        kind=RuleKind.LAW,
        status=RuleStatus.PASS,
        detail="Ms A: 0 prior + 5 proposed = 5 years; limit 10.",
        citation="Section 149(10)-(11), Companies Act 2013",
    )
]
HIT = RegulationHit(
    id="s149_10",
    source=RegulationSource.COMPANIES_ACT_2013,
    citation="Section 149(10), Companies Act 2013",
    heading="Term of independent director",
    text="An independent director shall hold office for a term up to five consecutive years.",
    applies_to=[ResolutionType.INDEPENDENT_DIRECTOR_APPOINT],
    source_url="https://example.org",
    score=0.9,
)
VALID = json.dumps(
    {
        "recommendation": "FOR",
        "confidence": 0.85,
        "rationale": "First five-year term, special resolution proposed.",
        "citations": [{"regulation_id": "s149_10", "quote": "a term up to five consecutive years"}],
    }
)


class Scripted:
    name = "scripted"
    model = "scripted-model"

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = replies
        self.calls: list[list[Message]] = []

    def generate_json(
        self, messages: list[Message], schema: dict[str, Any], schema_name: str
    ) -> LLMResponse:
        assert schema == REASONER_SCHEMA
        self.calls.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(reply, self.model)


def test_prompt_carries_findings_rules_and_excerpt_ids() -> None:
    rules = [r for r in load_policy() if r.id == "ID_TENURE_MAX"]

    prompt = build_reasoner_input(EXTRACTION, FINDINGS, rules, [HIT])

    assert "ID_TENURE_MAX (LAW, Section 149(10)-(11), Companies Act 2013): PASS" in prompt
    assert '"term_years": 5' in prompt
    assert "[s149_10] Section 149(10), Companies Act 2013." in prompt
    assert '"item_no": 4' in prompt


def test_reason_parses_valid_output() -> None:
    outcome = reason(Scripted([VALID]), EXTRACTION, FINDINGS, [], [HIT])

    assert outcome.output is not None
    assert outcome.output.recommendation == Recommendation.FOR
    assert outcome.output.citations[0].regulation_id == "s149_10"


def test_reason_repairs_once_with_the_error() -> None:
    provider = Scripted(['{"recommendation": "MAYBE"}', VALID])

    outcome = reason(provider, EXTRACTION, FINDINGS, [], [HIT])

    assert outcome.output is not None and len(outcome.raw_outputs) == 2
    repair = provider.calls[1][-1]
    assert repair.role == "user" and "recommendation" in repair.content


def test_reason_gives_up_after_one_repair_or_provider_error() -> None:
    bad = reason(Scripted(["nope", "still nope"]), EXTRACTION, FINDINGS, [], [])
    down = reason(Scripted([LLMError("503")]), EXTRACTION, FINDINGS, [], [])

    assert bad.output is None and bad.error and len(bad.raw_outputs) == 2
    assert down.output is None and down.error == "provider error: 503"
