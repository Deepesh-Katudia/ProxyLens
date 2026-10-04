"""Typed state passed between the LangGraph nodes (SPEC 3)."""

from pydantic import BaseModel, Field

from app.parsing.models import BusinessSection, MeetingType, ParsedNotice
from app.rules.models import CompanyFacts, RuleFinding
from app.schemas.analysis import Decision, ExtractorInfo, ItemAnalysis
from app.schemas.regulation import RegulationHit
from app.schemas.resolution import ResolutionExtraction

PIPELINE_VERSION = "0.5.0"


class Flag:
    """Analyst-facing pipeline warnings."""

    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    TEACHER_FALLBACK = "TEACHER_FALLBACK"
    ITEM_NO_MISMATCH = "ITEM_NO_MISMATCH"
    SPECIAL_RESOLUTION_MISMATCH = "SPECIAL_RESOLUTION_MISMATCH"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    REASONER_FAILED = "REASONER_FAILED"


class ItemState(BaseModel):
    """One agenda item as it moves through the graph."""

    seq: int
    item_no: int
    text: str
    explanatory_statement: str | None = None
    kind_hint: BusinessSection | None = None
    extraction: ResolutionExtraction | None = None
    extractor: ExtractorInfo | None = None
    findings: list[RuleFinding] = Field(default_factory=list)
    hits: list[RegulationHit] = Field(default_factory=list)
    decision: Decision | None = None
    flags: list[str] = Field(default_factory=list)

    def flagged(self, *flags: str) -> list[str]:
        return [*self.flags, *(f for f in flags if f not in self.flags)]


class PipelineState(BaseModel):
    pdf: bytes | None = None  # input; or pass `notice` directly
    notice: ParsedNotice | None = None
    company: CompanyFacts = Field(default_factory=CompanyFacts)
    items: list[ItemState] = Field(default_factory=list)
    analyses: list[ItemAnalysis] = Field(default_factory=list)

    @property
    def meeting_type(self) -> MeetingType:
        return self.notice.meeting_type if self.notice else MeetingType.UNKNOWN
