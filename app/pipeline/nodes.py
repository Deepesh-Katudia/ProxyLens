"""Pipeline nodes: parse -> extract -> validate -> retrieve -> rule_check -> reason ->
assemble (SPEC 3). Each node reads the state and returns only the keys it updates;
items are replaced with updated copies, never mutated."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.llm.base import LLMProvider
from app.llm.fallback import extract_with_fallback
from app.llm.reasoner import reason
from app.parsing.models import BusinessSection
from app.parsing.notice import parse_notice_pdf
from app.pipeline.constraints import enforce, needs_review
from app.pipeline.state import PIPELINE_VERSION, Flag, ItemState, PipelineState
from app.rules.engine import applicable_rules, evaluate
from app.rules.models import RuleContext, RuleSpec
from app.schemas.analysis import ExtractorInfo, ItemAnalysis
from app.schemas.regulation import RegulationHit
from app.schemas.resolution import ResolutionExtraction, ResolutionType

logger = logging.getLogger(__name__)

Retriever = Callable[[str, ResolutionType | None, int], Awaitable[list[RegulationHit]]]
Update = dict[str, Any]

RETRIEVAL_K = 6  # SPEC 6.2
MAX_QUERY_FACTS = 3


@dataclass(frozen=True)
class PipelineDeps:
    student: LLMProvider
    teacher: LLMProvider | None  # extraction fallback
    reasoner: LLMProvider | None  # None: every item ends as NEEDS_REVIEW
    retriever: Retriever
    rules: list[RuleSpec] = field(default_factory=list)
    k: int = RETRIEVAL_K


def parse(state: PipelineState) -> Update:
    notice = state.notice
    if notice is None:
        if state.pdf is None:
            raise ValueError("pipeline needs either `pdf` or `notice`")
        notice = parse_notice_pdf(state.pdf)
    items = [
        ItemState(
            seq=item.seq,
            item_no=item.item_no,
            text=item.text,
            explanatory_statement=item.explanatory_statement,
            kind_hint=item.resolution_kind_hint,
        )
        for item in notice.items
    ]
    return {"notice": notice, "items": items}


async def extract(state: PipelineState, deps: PipelineDeps) -> Update:
    items = []
    for item in state.items:  # sequential: llama.cpp contexts are not thread-safe
        result = await asyncio.to_thread(
            extract_with_fallback,
            deps.student,
            deps.teacher,
            item.item_no,
            item.text,
            item.explanatory_statement,
        )
        outcome = result.outcome
        served_by = deps.teacher if result.used_fallback and deps.teacher else deps.student
        fallback_ms = outcome.latency_ms if result.used_fallback else 0
        info = ExtractorInfo(
            provider=served_by.name,
            model=outcome.model,
            latency_ms=result.student.latency_ms + fallback_ms,
            valid_first_try=result.student.valid_first_try,
            used_fallback=result.used_fallback,
        )
        flags = item.flagged(Flag.TEACHER_FALLBACK) if result.used_fallback else item.flags
        update = {"extraction": outcome.extraction, "extractor": info, "flags": flags}
        items.append(item.model_copy(update=update))
    return {"items": items}


def _validated(item: ItemState) -> ItemState:
    extraction = item.extraction
    if extraction is None:
        return item.model_copy(update={"flags": item.flagged(Flag.EXTRACTION_FAILED)})
    fixes: dict[str, Any] = {}
    flags: list[str] = []
    if extraction.item_no != item.item_no:  # the notice's numbering is authoritative
        fixes["item_no"] = item.item_no
        flags.append(Flag.ITEM_NO_MISMATCH)
    if item.kind_hint is not None:  # "as a Special Resolution" in the notice text wins
        special = item.kind_hint == BusinessSection.SPECIAL
        if special != extraction.is_special_resolution:
            fixes["is_special_resolution"] = special
            flags.append(Flag.SPECIAL_RESOLUTION_MISMATCH)
    if not fixes:
        return item
    return item.model_copy(
        update={"extraction": extraction.model_copy(update=fixes), "flags": item.flagged(*flags)}
    )


def validate(state: PipelineState) -> Update:
    return {"items": [_validated(item) for item in state.items]}


def retrieval_query(extraction: ResolutionExtraction) -> str:
    facts = " ".join(extraction.key_facts[:MAX_QUERY_FACTS])
    kind = extraction.resolution_type.value.replace("_", " ").lower()
    return f"{extraction.title}. {kind}. {facts}".strip()


async def retrieve(state: PipelineState, deps: PipelineDeps) -> Update:
    items = []
    for item in state.items:
        if item.extraction is None:
            items.append(item)
            continue
        kind = item.extraction.resolution_type
        type_filter = None if kind == ResolutionType.OTHER else kind
        try:
            hits = await deps.retriever(retrieval_query(item.extraction), type_filter, deps.k)
        except Exception:  # degrade to no citations rather than fail the notice
            logger.exception("retrieval failed for item %s", item.seq)
            items.append(item.model_copy(update={"flags": item.flagged(Flag.RETRIEVAL_FAILED)}))
            continue
        items.append(item.model_copy(update={"hits": hits}))
    return {"items": items}


def rule_check(state: PipelineState, deps: PipelineDeps) -> Update:
    items = []
    for item in state.items:
        if item.extraction is None:
            items.append(item)
            continue
        context = RuleContext(
            extraction=item.extraction, meeting_type=state.meeting_type, company=state.company
        )
        items.append(item.model_copy(update={"findings": evaluate(deps.rules, context)}))
    return {"items": items}


async def _decide(item: ItemState, state: PipelineState, deps: PipelineDeps) -> ItemState:
    if item.extraction is None:
        decision = needs_review("The resolution could not be extracted.", item.findings)
        return item.model_copy(update={"decision": decision})
    if deps.reasoner is None:
        decision = needs_review("No reasoner model is configured.", item.findings)
        return item.model_copy(update={"decision": decision})
    context = RuleContext(
        extraction=item.extraction, meeting_type=state.meeting_type, company=state.company
    )
    outcome = await asyncio.to_thread(
        reason,
        deps.reasoner,
        item.extraction,
        item.findings,
        applicable_rules(deps.rules, context),
        item.hits,
    )
    if outcome.output is None:
        decision = needs_review(f"The reasoner failed: {outcome.error}", item.findings)
        return item.model_copy(
            update={"decision": decision, "flags": item.flagged(Flag.REASONER_FAILED)}
        )
    chunks = {hit.id: hit.text for hit in item.hits}
    return item.model_copy(update={"decision": enforce(outcome.output, item.findings, chunks)})


async def decide(state: PipelineState, deps: PipelineDeps) -> Update:
    return {"items": [await _decide(item, state, deps) for item in state.items]}


def assemble(state: PipelineState) -> Update:
    analyses = []
    for item in state.items:
        decision = item.decision or needs_review("The item was not analysed.", item.findings)
        extraction = item.extraction
        analyses.append(
            ItemAnalysis(
                seq=item.seq,
                item_no=item.item_no,
                title=extraction.title if extraction else item.text.split("\n", 1)[0][:200],
                resolution_type=extraction.resolution_type if extraction else None,
                extraction=extraction,
                extractor=item.extractor,
                recommendation=decision.recommendation,
                confidence=decision.confidence,
                rationale=decision.rationale,
                rule_findings=item.findings,
                citations=decision.citations,
                retrieved_ids=[hit.id for hit in item.hits],
                flags=item.flags,
                adjustments=decision.adjustments,
                pipeline_version=PIPELINE_VERSION,
            )
        )
    return {"analyses": analyses}
