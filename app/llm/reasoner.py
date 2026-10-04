"""LLM reasoner: recommend a vote from the extraction, rule findings and the
retrieved regulations (SPEC 6.2). Hard constraints are applied afterwards by
app.pipeline.constraints, never trusted to the model."""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from app.llm.base import LLMError, LLMProvider, Message, Usage
from app.llm.prompts import repair_message
from app.llm.schema import parse_json_object, strict_json_schema
from app.rules.models import RuleFinding, RuleSpec
from app.schemas.analysis import ReasonerOutput
from app.schemas.regulation import RegulationHit
from app.schemas.resolution import ResolutionExtraction

SCHEMA_NAME = "VoteRecommendation"
REASONER_SCHEMA = strict_json_schema(ReasonerOutput)
MAX_ATTEMPTS = 2  # first try + one repair
MAX_CHUNK_CHARS = 2500

REASONER_SYSTEM_PROMPT = """You are a proxy-voting analyst for Indian listed companies. For one \
general-meeting resolution you receive: the structured extraction, the findings of \
deterministic rule checks, the house-policy rules that apply, and regulation excerpts \
retrieved from SEBI LODR 2015 and the Companies Act 2013. Recommend how an institutional \
investor should vote. Reply with one JSON object only.

Fields:
- recommendation: FOR, AGAINST, ABSTAIN or NEEDS_REVIEW.
- confidence: 0.0-1.0, how well the given facts support the recommendation.
- rationale: 2-5 sentences. Name the decisive facts and rules.
- citations: regulation excerpts that support the rationale. regulation_id must be one of the \
given ids, and quote must be copied verbatim from that excerpt (one sentence or clause, under \
40 words). Use [] when no excerpt is relevant.

Rules:
- A LAW rule with status FAIL means the resolution breaches the law or a SEBI regulation: never \
recommend FOR.
- INSUFFICIENT_DATA is not a pass. If a LAW rule lacks data, recommend NEEDS_REVIEW.
- POLICY rules are house guidelines: a FAIL argues for AGAINST unless the facts justify an \
exception, which the rationale must state.
- Routine items with no failed rules (adopting audited accounts, a dividend within policy) are \
normally FOR.
- Use only the given material. Do not invent facts, figures or regulations."""


@dataclass(frozen=True)
class ReasonerOutcome:
    output: ReasonerOutput | None
    raw_outputs: tuple[str, ...]
    error: str | None
    model: str
    usage: Usage
    latency_ms: int


def _excerpt(hit: RegulationHit) -> str:
    text = hit.text if len(hit.text) <= MAX_CHUNK_CHARS else hit.text[:MAX_CHUNK_CHARS] + " [...]"
    return f"[{hit.id}] {hit.citation}. {hit.heading}\n{text}"


def build_reasoner_input(
    extraction: ResolutionExtraction,
    findings: Sequence[RuleFinding],
    rules: Sequence[RuleSpec],
    hits: Sequence[RegulationHit],
) -> str:
    finding_lines = [
        f"- {f.rule_id} ({f.kind.value}, {f.citation}): {f.status.value}. {f.detail}"
        for f in findings
    ] or ["(no rules apply to this resolution type)"]
    policy_lines = [
        f"- {r.id} ({r.kind.value}): {r.citation}; params {json.dumps(r.params)}"
        + (f"; note: {r.notes}" if r.notes else "")
        for r in rules
    ] or ["(none)"]
    excerpts = [_excerpt(h) for h in hits] or ["(no regulation retrieved)"]
    return "\n\n".join(
        [
            "RESOLUTION (extracted):\n" + extraction.model_dump_json(indent=1),
            "RULE FINDINGS:\n" + "\n".join(finding_lines),
            "APPLICABLE RULES (config/policy.yaml):\n" + "\n".join(policy_lines),
            "REGULATION EXCERPTS:\n" + "\n\n".join(excerpts),
        ]
    )


def _validate(text: str) -> ReasonerOutput:
    try:
        return ReasonerOutput.model_validate(parse_json_object(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def reason(
    provider: LLMProvider,
    extraction: ResolutionExtraction,
    findings: Sequence[RuleFinding],
    rules: Sequence[RuleSpec],
    hits: Sequence[RegulationHit],
) -> ReasonerOutcome:
    messages = [
        Message("system", REASONER_SYSTEM_PROMPT),
        Message("user", build_reasoner_input(extraction, findings, rules, hits)),
    ]
    outputs: list[str] = []
    usage = Usage()
    latency = 0
    model = provider.model
    error: str | None = None
    for _ in range(MAX_ATTEMPTS):
        try:
            response = provider.generate_json(messages, REASONER_SCHEMA, SCHEMA_NAME)
        except LLMError as exc:
            error = f"provider error: {exc}"
            break
        outputs.append(response.text)
        usage += response.usage
        latency += response.latency_ms
        model = response.model
        try:
            output = _validate(response.text)
        except ValueError as exc:
            error = str(exc)
            messages += [
                Message("assistant", response.text),
                Message("user", repair_message(error)),
            ]
            continue
        return ReasonerOutcome(output, tuple(outputs), None, model, usage, latency)
    return ReasonerOutcome(None, tuple(outputs), error, model, usage, latency)
