"""API-facing records for uploaded notices and their analyses (SPEC 5, 9)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.parsing.models import MeetingType
from app.rules.models import CompanyFacts, RuleFinding
from app.schemas.analysis import Citation, ExtractorInfo, Recommendation
from app.schemas.resolution import ResolutionExtraction


class JobStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    EXTRACTING = "extracting"
    ANALYSING = "analysing"
    DONE = "done"
    FAILED = "failed"


class Job(BaseModel):
    id: str
    document_id: str
    status: JobStatus
    done: int = 0  # items finished in the current stage
    total: int = 0
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentMeta(BaseModel):
    id: str
    filename: str
    file_sha256: str
    company: str | None = None
    meeting_type: MeetingType | None = None
    pages: int | None = None
    item_count: int | None = None
    company_facts: CompanyFacts = Field(default_factory=CompanyFacts)
    job_id: str | None = None
    uploaded_at: datetime


class Resolution(BaseModel):
    id: str
    document_id: str
    seq: int
    item_no: int
    raw_text: str
    explanatory_statement: str | None = None
    extracted: ResolutionExtraction | None = None
    extractor: ExtractorInfo | None = None


class Analysis(BaseModel):
    id: str
    resolution_id: str
    document_id: str
    recommendation: Recommendation
    confidence: float
    rationale: str
    rule_findings: list[RuleFinding]
    citations: list[Citation]
    retrieved_ids: list[str]
    flags: list[str]
    adjustments: list[str]
    pipeline_version: str
    created_at: datetime


class FeedbackIn(BaseModel):
    """An analyst's override of one analysis."""

    analyst_recommendation: Recommendation
    reason: str = Field(min_length=3, max_length=2000)
    corrected_extraction: ResolutionExtraction | None = None


class Feedback(FeedbackIn):
    id: str
    analysis_id: str
    created_at: datetime


class ReportItem(BaseModel):
    resolution: Resolution
    analysis: Analysis | None = None
    feedback: list[Feedback] = Field(default_factory=list)  # newest last


class DocumentReport(BaseModel):
    document: DocumentMeta
    job: Job | None = None
    items: list[ReportItem]
