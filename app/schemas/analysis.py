"""Decision and analysis models (SPEC 5 `analyses`, SPEC 6.2 reasoner output)."""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.rules.models import RuleFinding
from app.schemas.resolution import ResolutionExtraction, ResolutionType


class Recommendation(StrEnum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class Citation(BaseModel):
    regulation_id: str
    quote: str  # verbatim span of the cited chunk


class ReasonerOutput(BaseModel):
    """What the LLM reasoner must return (validated before any constraint runs)."""

    recommendation: Recommendation
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citations: list[Citation] = Field(default_factory=list)


class Decision(ReasonerOutput):
    """The reasoner's output after the hard constraints of SPEC 6.2 are enforced."""

    adjustments: list[str] = Field(default_factory=list)  # what enforcement changed, and why


class ExtractorInfo(BaseModel):
    provider: str
    model: str
    latency_ms: int
    valid_first_try: bool
    used_fallback: bool


class ItemAnalysis(BaseModel):
    """One agenda item's full result: extraction, rule findings and recommendation."""

    seq: int
    item_no: int
    title: str
    resolution_type: ResolutionType | None
    extraction: ResolutionExtraction | None
    extractor: ExtractorInfo | None
    recommendation: Recommendation
    confidence: float
    rationale: str
    rule_findings: list[RuleFinding]
    citations: list[Citation]
    retrieved_ids: list[str]
    flags: list[str]  # pipeline warnings for the analyst, e.g. EXTRACTION_FAILED
    adjustments: list[str]
    pipeline_version: str
