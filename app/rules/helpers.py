"""Small helpers shared by the rule checks."""

import re
from collections.abc import Iterable

from app.rules.models import CheckResult, RuleStatus
from app.schemas.resolution import Person, ResolutionExtraction

CRORE = 10_000_000

_REAPPOINT = re.compile(r"\bre[-\s]?appoint", re.IGNORECASE)
_EXECUTIVE_ROLES = (
    "managing director",
    "whole-time",
    "whole time",
    "wholetime",
    "executive director",
    "executive chairman",
    "manager",
    "chief executive",
    "ceo",
)
_NON_EXECUTIVE = re.compile(r"non[-\s]?executive", re.IGNORECASE)
_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3}
_TERM_NUMBER = re.compile(r"\b(first|1st|second|2nd|third|3rd)\s+term\b", re.IGNORECASE)

# Severity order used when per-person results are combined into one verdict.
_SEVERITY = {
    RuleStatus.FAIL: 3,
    RuleStatus.INSUFFICIENT_DATA: 2,
    RuleStatus.PASS: 1,
    RuleStatus.NA: 0,
}


def text_of(extraction: ResolutionExtraction) -> str:
    """Title and key facts: the free text checks may look for wording in."""
    return " ".join([extraction.title, *extraction.key_facts])


def is_reappointment(extraction: ResolutionExtraction) -> bool:
    return bool(_REAPPOINT.search(text_of(extraction)))


def stated_term_number(extraction: ResolutionExtraction) -> int | None:
    """1, 2 or 3 when the text says "first/second/third term", else None."""
    match = _TERM_NUMBER.search(text_of(extraction))
    return _ORDINALS[match.group(1).lower()] if match else None


def prior_years(
    stated: float | None, extraction: ResolutionExtraction, term_years: float
) -> tuple[float | None, str]:
    """Years already served: as stated, else inferred from "second term" wording, else 0
    for a first appointment. None when a re-appointment gives no way to tell."""
    if stated is not None:
        return stated, ""
    if (number := stated_term_number(extraction)) is not None:
        return (number - 1) * term_years, f" (inferred from 'term {number}')"
    if is_reappointment(extraction):
        return None, ""
    return 0.0, " (treated as a first appointment)"


def is_executive(person: Person) -> bool | None:
    """True for MD / WTD / manager roles, False for non-executive, None if unknown."""
    if not person.role:
        return None
    role = person.role.lower()
    if _NON_EXECUTIVE.search(role):
        return False
    return any(marker in role for marker in _EXECUTIVE_ROLES)


def crore(amount_inr: float) -> str:
    return f"Rs {amount_inr / CRORE:,.2f} crore"


def result(status: RuleStatus, detail: str) -> CheckResult:
    return CheckResult(status=status, detail=detail)


def combine(results: Iterable[CheckResult], empty_detail: str) -> CheckResult:
    """Merge per-person results: the most severe status wins; details are joined."""
    items = list(results)
    if not items:
        return result(RuleStatus.INSUFFICIENT_DATA, empty_detail)
    worst = max(items, key=lambda r: _SEVERITY[r.status]).status
    return result(worst, " ".join(r.detail for r in items))
