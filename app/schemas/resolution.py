"""Resolution extraction schema (SPEC 5.1). Also the fine-tuning target format."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ResolutionType(StrEnum):
    ADOPT_FINANCIALS = "ADOPT_FINANCIALS"
    DIVIDEND = "DIVIDEND"
    DIRECTOR_REAPPOINT_ROTATION = "DIRECTOR_REAPPOINT_ROTATION"
    INDEPENDENT_DIRECTOR_APPOINT = "INDEPENDENT_DIRECTOR_APPOINT"
    NON_INDEPENDENT_DIRECTOR_APPOINT = "NON_INDEPENDENT_DIRECTOR_APPOINT"
    MANAGERIAL_REMUNERATION = "MANAGERIAL_REMUNERATION"
    RELATED_PARTY_TRANSACTION = "RELATED_PARTY_TRANSACTION"
    AUDITOR_APPOINT = "AUDITOR_APPOINT"
    AUDITOR_REMUNERATION_COST = "AUDITOR_REMUNERATION_COST"  # cost auditor ratification
    ESOP = "ESOP"
    CAPITAL_RAISE = "CAPITAL_RAISE"  # QIP, preferential, NCDs
    BORROWING_LIMITS = "BORROWING_LIMITS"  # Sec 180
    ARTICLES_OR_MOA_AMENDMENT = "ARTICLES_OR_MOA_AMENDMENT"
    OTHER = "OTHER"


class Person(BaseModel):
    name: str
    role: str | None = None
    age: int | None = None
    din: str | None = None
    is_promoter: bool | None = None
    tenure_years_proposed: float | None = None
    prior_tenure_years: float | None = None
    board_attendance_pct: float | None = None


class Money(BaseModel):
    amount_inr: float | None = None  # normalized to INR (crore/lakh -> INR)
    raw: str


class ResolutionExtraction(BaseModel):
    item_no: int
    title: str
    resolution_type: ResolutionType
    is_special_resolution: bool
    persons: list[Person] = Field(default_factory=list)
    amounts: list[Money] = Field(default_factory=list)
    counterparty: str | None = None
    counterparty_is_related: bool | None = None
    transaction_nature: str | None = None
    duration_years: float | None = None
    key_facts: list[str] = Field(default_factory=list, max_length=5)
