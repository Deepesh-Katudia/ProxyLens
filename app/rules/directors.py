"""Director checks: independent-director tenure and approval, age 75, periodic
approval and attendance (config/policy.yaml)."""

import re

from app.rules.helpers import (
    combine,
    is_executive,
    is_reappointment,
    prior_years,
    result,
    text_of,
)
from app.rules.models import CheckResult, RuleContext, RuleSpec, RuleStatus
from app.schemas.resolution import Person, ResolutionType

_ROTATION = re.compile(r"retire[sd]?\s+by\s+rotation", re.IGNORECASE)
_NO_PERSON = "No director identified in the extraction."


def _proposed_years(person: Person, ctx: RuleContext) -> float | None:
    if person.tenure_years_proposed is not None:
        return person.tenure_years_proposed
    return ctx.extraction.duration_years


def id_tenure_max(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """s.149(10)-(11): terms of up to 5 years, at most two consecutive terms."""
    term = float(spec.params["term_years"])
    limit = term * int(spec.params["max_consecutive_terms"])

    def one(person: Person) -> CheckResult:
        proposed = _proposed_years(person, ctx)
        if proposed is None:
            return result(RuleStatus.INSUFFICIENT_DATA, f"{person.name}: proposed term not stated.")
        if proposed > term:
            return result(
                RuleStatus.FAIL,
                f"{person.name}: proposed term of {proposed:g} years exceeds {term:g} years.",
            )
        prior, assumed = prior_years(person.prior_tenure_years, ctx.extraction, term)
        if prior is None:
            return result(
                RuleStatus.INSUFFICIENT_DATA,
                f"{person.name}: re-appointment, but prior tenure is not stated.",
            )
        total = prior + proposed
        status = RuleStatus.FAIL if total > limit else RuleStatus.PASS
        return result(
            status,
            f"{person.name}: {prior:g} prior + {proposed:g} proposed = {total:g} years{assumed}; "
            f"limit {limit:g}.",
        )

    return combine(map(one, ctx.extraction.persons), _NO_PERSON)


def id_special_resolution(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """Reg 25(2A): every independent-director (re-)appointment needs a special resolution."""
    if ctx.extraction.is_special_resolution:
        return result(RuleStatus.PASS, "Proposed as a special resolution.")
    return result(RuleStatus.FAIL, "Proposed as an ordinary resolution; a special one is required.")


def ned_age_special(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """Reg 17(1A): a non-executive director aged 75+ needs a special resolution."""
    threshold = int(spec.params["age_years"])
    special = ctx.extraction.is_special_resolution

    def one(person: Person) -> CheckResult:
        executive = is_executive(person)
        if executive:
            return result(RuleStatus.NA, f"{person.name}: executive director, not covered.")
        if person.age is None:
            return result(RuleStatus.INSUFFICIENT_DATA, f"{person.name}: age not stated.")
        if person.age < threshold:
            return result(RuleStatus.NA, f"{person.name}: aged {person.age}, below {threshold}.")
        if special:
            return result(
                RuleStatus.PASS, f"{person.name}: aged {person.age}; special resolution proposed."
            )
        if executive is None:
            return result(
                RuleStatus.INSUFFICIENT_DATA,
                f"{person.name}: aged {person.age}, ordinary resolution, role not stated.",
            )
        return result(
            RuleStatus.FAIL,
            f"{person.name}: non-executive, aged {person.age}, but only an ordinary resolution.",
        )

    return combine(map(one, ctx.extraction.persons), _NO_PERSON)


def director_periodic_approval(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """Reg 17(1D): continuation approved at least every 5 years (with exclusions)."""
    extraction = ctx.extraction
    if extraction.resolution_type in (
        ResolutionType.DIRECTOR_REAPPOINT_ROTATION,
        ResolutionType.INDEPENDENT_DIRECTOR_APPOINT,
    ):
        return result(
            RuleStatus.NA,
            "Directors retiring by rotation and independent directors are excluded.",
        )
    if _ROTATION.search(text_of(extraction)):
        return result(RuleStatus.NA, "Director is liable to retire by rotation; excluded.")
    limit = float(spec.params["max_years_between_approvals"])

    def one(person: Person) -> CheckResult:
        if is_executive(person):
            return result(RuleStatus.NA, f"{person.name}: MD/WTD/manager, excluded.")
        proposed = _proposed_years(person, ctx)
        if proposed is None:
            return result(
                RuleStatus.INSUFFICIENT_DATA,
                f"{person.name}: neither a term nor retirement by rotation is stated.",
            )
        status = RuleStatus.FAIL if proposed > limit else RuleStatus.PASS
        return result(
            status, f"{person.name}: approval covers {proposed:g} years; limit {limit:g}."
        )

    return combine(map(one, extraction.persons), _NO_PERSON)


def attendance_min(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """House policy: re-appointed directors need board attendance of at least N%."""
    extraction = ctx.extraction
    rotation = extraction.resolution_type == ResolutionType.DIRECTOR_REAPPOINT_ROTATION
    if not (rotation or is_reappointment(extraction)):
        return result(RuleStatus.NA, "First appointment; no attendance record to assess.")
    minimum = float(spec.params["min_attendance_pct"])

    def one(person: Person) -> CheckResult:
        pct = person.board_attendance_pct
        if pct is None:
            return result(RuleStatus.INSUFFICIENT_DATA, f"{person.name}: attendance not stated.")
        status = RuleStatus.FAIL if pct < minimum else RuleStatus.PASS
        return result(status, f"{person.name}: attendance {pct:g}%; minimum {minimum:g}%.")

    return combine(map(one, extraction.persons), _NO_PERSON)
