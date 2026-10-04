"""Rule-engine data structures (SPEC 6.1)."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.parsing.models import MeetingType
from app.schemas.resolution import ResolutionExtraction, ResolutionType


class RuleKind(StrEnum):
    LAW = "LAW"  # statutory / regulatory requirement
    POLICY = "POLICY"  # house voting guideline


class RuleStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "NA"  # the rule applies to the resolution type but not to these facts
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # never treated as a pass


class RuleSpec(BaseModel):
    """One rule as declared in config/policy.yaml."""

    id: str
    applies_to: list[ResolutionType]
    kind: RuleKind
    check: str  # name of a function in app.rules.checks.CHECKS
    params: dict[str, Any] = Field(default_factory=dict)
    citation: str
    source_url: str | None
    as_of: str
    verified: bool = False
    notes: str | None = None


class CompanyFacts(BaseModel):
    """Company figures some thresholds depend on. Not in the notice extraction;
    unknown values make the dependent checks return INSUFFICIENT_DATA."""

    turnover_inr: float | None = None  # consolidated turnover, last audited year
    net_profit_inr: float | None = None  # net profit computed under s.198


class RuleContext(BaseModel):
    extraction: ResolutionExtraction
    meeting_type: MeetingType = MeetingType.UNKNOWN
    company: CompanyFacts = Field(default_factory=CompanyFacts)


class CheckResult(BaseModel):
    status: RuleStatus
    detail: str


class RuleFinding(BaseModel):
    """A rule's verdict on one resolution, as stored in `analyses.rule_findings`."""

    rule_id: str
    kind: RuleKind
    status: RuleStatus
    detail: str
    citation: str
    source_url: str | None = None
    verified: bool = False
