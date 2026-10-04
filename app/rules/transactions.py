"""Related-party transaction checks (Reg 23, Schedule XII; house policy)."""

import re
from typing import Any

from app.parsing.models import MeetingType
from app.rules.helpers import CRORE, crore, result, text_of
from app.rules.models import CheckResult, RuleContext, RuleSpec, RuleStatus

_RATIFY = re.compile(r"\bratif", re.IGNORECASE)
_MATERIALITY_LABEL = {
    True: "material",
    False: "below the materiality threshold",
    None: "of unknown materiality",
}


def _largest_amount(ctx: RuleContext) -> float | None:
    values = [m.amount_inr for m in ctx.extraction.amounts if m.amount_inr is not None]
    return max(values) if values else None


def materiality_threshold_inr(turnover_inr: float, tiers: list[dict[str, Any]]) -> float:
    """Schedule XII threshold for a given consolidated turnover (tiers in crore)."""
    turnover = turnover_inr / CRORE
    for tier in tiers:
        if tier["turnover_up_to"] is None or turnover <= tier["turnover_up_to"]:
            threshold = tier["base"] + tier["pct_of_turnover_above"] / 100 * (
                turnover - tier["above"]
            )
            if tier.get("cap") is not None:
                threshold = min(threshold, tier["cap"])
            return float(threshold * CRORE)
    raise ValueError("materiality tiers must end with an open-ended tier")


def _is_material(value: float, ctx: RuleContext, tiers: list[dict[str, Any]]) -> bool | None:
    caps = [tier["cap"] for tier in tiers if tier.get("cap") is not None]
    if caps and value > max(caps) * CRORE:
        return True  # above the highest possible threshold, whatever the turnover
    if ctx.company.turnover_inr is None:
        return None
    return value > materiality_threshold_inr(ctx.company.turnover_inr, tiers)


def _not_related(ctx: RuleContext) -> CheckResult | None:
    related = ctx.extraction.counterparty_is_related
    if related is False:
        return result(RuleStatus.NA, "Counterparty is stated not to be a related party.")
    if related is None:
        return result(
            RuleStatus.INSUFFICIENT_DATA, "Whether the counterparty is related is not stated."
        )
    return None


def rpt_material_approval(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """Reg 23(4): material RPTs need *prior* shareholder approval."""
    if (early := _not_related(ctx)) is not None:
        return early
    value = _largest_amount(ctx)
    if value is None:
        return result(RuleStatus.INSUFFICIENT_DATA, "Transaction value not stated.")
    material = _is_material(value, ctx, spec.params["materiality_tiers_inr_crore"])
    size = _MATERIALITY_LABEL[material]
    if _RATIFY.search(text_of(ctx.extraction)):
        if material:
            return result(
                RuleStatus.FAIL,
                f"Seeks ratification of a material RPT ({crore(value)}); "
                "prior approval is required.",
            )
        if material is None:
            return result(
                RuleStatus.INSUFFICIENT_DATA,
                f"Seeks ratification of {crore(value)}; company turnover is needed to tell "
                "whether prior approval was required.",
            )
    return result(
        RuleStatus.PASS,
        f"Prior approval sought for {crore(value)} ({size}); "
        "related parties may not vote in favour.",
    )


def rpt_omnibus_validity(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """Reg 23(4) provisos: AGM approvals last until the next AGM, others at most 1 year."""
    if (early := _not_related(ctx)) is not None:
        return early
    years = ctx.extraction.duration_years
    if years is None:
        return result(RuleStatus.INSUFFICIENT_DATA, "Approval period not stated.")
    agm_limit = float(spec.params["agm_max_years"])
    other_limit = float(spec.params["other_meeting_max_years"])
    if ctx.meeting_type == MeetingType.AGM:
        limit = agm_limit
    elif ctx.meeting_type == MeetingType.UNKNOWN and other_limit < years <= agm_limit:
        return result(
            RuleStatus.INSUFFICIENT_DATA,
            f"Approval for {years:g} years is valid only at an AGM; meeting type unknown.",
        )
    else:
        limit = other_limit
    status = RuleStatus.FAIL if years > limit else RuleStatus.PASS
    return result(status, f"Approval for {years:g} years; limit {limit:g} at this meeting.")


def rpt_no_cap(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """House policy: an RPT approval must carry a monetary cap."""
    if (early := _not_related(ctx)) is not None and early.status == RuleStatus.NA:
        return early
    value = _largest_amount(ctx)
    if value is None:
        return result(RuleStatus.FAIL, "No monetary cap found in the resolution.")
    return result(RuleStatus.PASS, f"Capped at {crore(value)}.")
