"""Auditor rotation check (s.139(2), Companies Act 2013)."""

import re

from app.rules.helpers import prior_years, result
from app.rules.models import CheckResult, RuleContext, RuleSpec, RuleStatus

_FIRM = re.compile(r"\bLLP\b|&|\bCo\b\.?|\bAssociates\b|\bPartners\b|\bFirm\b", re.IGNORECASE)


def _auditor_name(ctx: RuleContext) -> str | None:
    """The auditor from the persons list or counterparty; else a firm named in the title."""
    extraction = ctx.extraction
    if extraction.persons:
        return extraction.persons[0].name
    if extraction.counterparty:
        return extraction.counterparty
    return extraction.title if _FIRM.search(extraction.title) else None


def auditor_rotation(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """An individual auditor gets one 5-year term, an audit firm two."""
    extraction = ctx.extraction
    person = extraction.persons[0] if extraction.persons else None
    name = _auditor_name(ctx)
    if not name:
        return result(RuleStatus.INSUFFICIENT_DATA, "Auditor not identified.")
    term = float(spec.params["term_years"])
    is_firm = bool(_FIRM.search(name))
    terms = int(spec.params["firm_max_terms" if is_firm else "individual_max_terms"])
    limit = term * terms
    kind = "audit firm" if is_firm else "individual auditor"

    proposed = extraction.duration_years
    if proposed is None and person is not None:
        proposed = person.tenure_years_proposed
    if proposed is None:
        return result(RuleStatus.INSUFFICIENT_DATA, f"{name}: term not stated.")
    if proposed > term:
        return result(
            RuleStatus.FAIL, f"{name}: proposed term of {proposed:g} years exceeds {term:g}."
        )
    prior, assumed = prior_years(person.prior_tenure_years if person else None, extraction, term)
    if prior is None:
        return result(
            RuleStatus.INSUFFICIENT_DATA,
            f"{name}: re-appointment, but years already served are not stated.",
        )
    total = prior + proposed
    status = RuleStatus.FAIL if total > limit else RuleStatus.PASS
    return result(
        status,
        f"{name} ({kind}): {prior:g} served + {proposed:g} proposed = {total:g} years{assumed}; "
        f"limit {limit:g}.",
    )
