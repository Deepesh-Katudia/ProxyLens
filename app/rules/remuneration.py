"""Managerial remuneration checks (Reg 17(6)(e); house policy)."""

import re

from app.rules.helpers import CRORE, crore, is_executive, result, text_of
from app.rules.models import CheckResult, RuleContext, RuleSpec, RuleStatus

_INCREASE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*(?:increase|hike|rise)|(?:increase|hike|rise)\s+of\s+(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_ANNUAL_NOTE = " The largest stated amount is taken as annual pay."


def _largest_amount(ctx: RuleContext) -> float | None:
    values = [m.amount_inr for m in ctx.extraction.amounts if m.amount_inr is not None]
    return max(values) if values else None


def exec_promoter_pay_special(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """Reg 17(6)(e): executive promoter-director pay above max(Rs 5 cr, 2.5% of net
    profit) needs a special resolution."""
    extraction = ctx.extraction
    if extraction.is_special_resolution:
        return result(RuleStatus.PASS, "Proposed as a special resolution.")
    if not extraction.persons:
        return result(RuleStatus.INSUFFICIENT_DATA, "No director identified in the extraction.")
    promoters = [p for p in extraction.persons if p.is_promoter and is_executive(p) is not False]
    if not promoters:
        if any(p.is_promoter is None for p in extraction.persons):
            return result(RuleStatus.INSUFFICIENT_DATA, "Promoter status not stated.")
        return result(RuleStatus.NA, "No executive promoter director.")
    names = ", ".join(p.name for p in promoters)
    value = _largest_amount(ctx)
    if value is None:
        return result(RuleStatus.INSUFFICIENT_DATA, f"{names}: remuneration amount not stated.")
    floor = float(spec.params["individual_inr_crore"]) * CRORE
    if value <= floor:
        return result(
            RuleStatus.PASS,
            f"{names}: {crore(value)} is within the Rs {floor / CRORE:g} crore floor."
            + _ANNUAL_NOTE,
        )
    if ctx.company.net_profit_inr is None:
        return result(
            RuleStatus.INSUFFICIENT_DATA,
            f"{names}: {crore(value)} exceeds Rs {floor / CRORE:g} crore; net profit is needed "
            f"for the {spec.params['individual_pct_net_profit']}% test.{_ANNUAL_NOTE}",
        )
    pct = float(spec.params["individual_pct_net_profit"])
    threshold = max(floor, pct / 100 * ctx.company.net_profit_inr)
    status = RuleStatus.FAIL if value > threshold else RuleStatus.PASS
    return result(
        status,
        f"{names}: {crore(value)} vs threshold {crore(threshold)}; ordinary resolution."
        + _ANNUAL_NOTE,
    )


def pay_jump(spec: RuleSpec, ctx: RuleContext) -> CheckResult:
    """House policy: flag uncapped pay or a year-on-year rise above N%."""
    if spec.params.get("require_cap", True) and _largest_amount(ctx) is None:
        return result(RuleStatus.FAIL, "No monetary cap on remuneration found.")
    increases = [float(a or b) for a, b in _INCREASE.findall(text_of(ctx.extraction))]
    if not increases:
        return result(
            RuleStatus.INSUFFICIENT_DATA, "Remuneration is capped; year-on-year change not stated."
        )
    limit = float(spec.params["max_yoy_increase_pct"])
    rise = max(increases)
    status = RuleStatus.FAIL if rise > limit else RuleStatus.PASS
    return result(status, f"Stated increase {rise:g}%; limit {limit:g}%.")
