from pathlib import Path
from typing import Any

import pytest
import yaml

from app.parsing.models import MeetingType
from app.rules.engine import CHECKS, PolicyError, evaluate, load_policy
from app.rules.models import CompanyFacts, RuleContext, RuleKind, RuleSpec, RuleStatus
from app.rules.transactions import materiality_threshold_inr
from app.schemas.resolution import Money, Person, ResolutionExtraction, ResolutionType

CR = 10_000_000
P = RuleStatus.PASS
F = RuleStatus.FAIL
NA = RuleStatus.NA
INS = RuleStatus.INSUFFICIENT_DATA

RULES = {rule.id: rule for rule in load_policy()}


def ctx(
    resolution_type: ResolutionType,
    *,
    title: str = "Item",
    special: bool = False,
    persons: list[Person] | None = None,
    amounts_cr: list[float] | None = None,
    related: bool | None = None,
    duration: float | None = None,
    facts: list[str] | None = None,
    counterparty: str | None = None,
    meeting: MeetingType = MeetingType.AGM,
    turnover_cr: float | None = None,
    net_profit_cr: float | None = None,
) -> RuleContext:
    extraction = ResolutionExtraction(
        item_no=1,
        title=title,
        resolution_type=resolution_type,
        is_special_resolution=special,
        persons=persons or [],
        amounts=[Money(amount_inr=a * CR, raw=f"Rs {a} crore") for a in amounts_cr or []],
        counterparty=counterparty,
        counterparty_is_related=related,
        duration_years=duration,
        key_facts=facts or [],
    )
    company = CompanyFacts(
        turnover_inr=turnover_cr * CR if turnover_cr is not None else None,
        net_profit_inr=net_profit_cr * CR if net_profit_cr is not None else None,
    )
    return RuleContext(extraction=extraction, meeting_type=meeting, company=company)


def person(**kwargs: Any) -> Person:
    return Person(name=kwargs.pop("name", "A Director"), **kwargs)


ID = ResolutionType.INDEPENDENT_DIRECTOR_APPOINT
NID = ResolutionType.NON_INDEPENDENT_DIRECTOR_APPOINT
ROT = ResolutionType.DIRECTOR_REAPPOINT_ROTATION
RPT = ResolutionType.RELATED_PARTY_TRANSACTION
PAY = ResolutionType.MANAGERIAL_REMUNERATION
AUD = ResolutionType.AUDITOR_APPOINT
FIRM = "M/s Rao & Co. LLP"

CASES: list[tuple[str, RuleContext, RuleStatus]] = [
    # ID_TENURE_MAX: two terms of up to 5 years
    (
        "ID_TENURE_MAX",
        ctx(
            ID,
            title="Re-appointment",
            persons=[person(prior_tenure_years=5, tenure_years_proposed=5)],
        ),
        P,
    ),
    (
        "ID_TENURE_MAX",
        ctx(
            ID,
            title="Re-appointment",
            persons=[person(prior_tenure_years=6, tenure_years_proposed=5)],
        ),
        F,
    ),
    ("ID_TENURE_MAX", ctx(ID, persons=[person(tenure_years_proposed=6)]), F),
    ("ID_TENURE_MAX", ctx(ID, title="Appointment", persons=[person(tenure_years_proposed=5)]), P),
    (
        "ID_TENURE_MAX",
        ctx(ID, title="Re-appointment", persons=[person(tenure_years_proposed=5)]),
        INS,
    ),
    ("ID_TENURE_MAX", ctx(ID, persons=[person()]), INS),
    ("ID_TENURE_MAX", ctx(ID), INS),
    # ID_SPECIAL_RESOLUTION: Reg 25(2A)
    ("ID_SPECIAL_RESOLUTION", ctx(ID, special=True), P),
    ("ID_SPECIAL_RESOLUTION", ctx(ID, special=False), F),
    # NED_AGE_75_SPECIAL
    ("NED_AGE_75_SPECIAL", ctx(NID, persons=[person(age=60)]), NA),
    ("NED_AGE_75_SPECIAL", ctx(NID, persons=[person(age=80, role="Managing Director")]), NA),
    ("NED_AGE_75_SPECIAL", ctx(NID, special=True, persons=[person(age=80)]), P),
    ("NED_AGE_75_SPECIAL", ctx(NID, persons=[person(age=80, role="Non-Executive Director")]), F),
    ("NED_AGE_75_SPECIAL", ctx(NID, persons=[person(age=80)]), INS),
    ("NED_AGE_75_SPECIAL", ctx(NID, persons=[person()]), INS),
    # DIRECTOR_PERIODIC_APPROVAL: Reg 17(1D), with its exclusions
    ("DIRECTOR_PERIODIC_APPROVAL", ctx(ROT, persons=[person()]), NA),
    (
        "DIRECTOR_PERIODIC_APPROVAL",
        ctx(NID, persons=[person()], facts=["Liable to retire by rotation."]),
        NA,
    ),
    ("DIRECTOR_PERIODIC_APPROVAL", ctx(NID, persons=[person(role="Whole-time Director")]), NA),
    ("DIRECTOR_PERIODIC_APPROVAL", ctx(NID, persons=[person(tenure_years_proposed=5)]), P),
    ("DIRECTOR_PERIODIC_APPROVAL", ctx(NID, persons=[person()], duration=6), F),
    ("DIRECTOR_PERIODIC_APPROVAL", ctx(NID, persons=[person()]), INS),
    # POL_ATTENDANCE_MIN
    ("POL_ATTENDANCE_MIN", ctx(NID, title="Appointment", persons=[person()]), NA),
    ("POL_ATTENDANCE_MIN", ctx(ROT, persons=[person(board_attendance_pct=90)]), P),
    (
        "POL_ATTENDANCE_MIN",
        ctx(ID, title="Re-appointment", persons=[person(board_attendance_pct=60)]),
        F,
    ),
    ("POL_ATTENDANCE_MIN", ctx(ROT, persons=[person()]), INS),
    # RPT_MATERIAL_APPROVAL: prior approval of material RPTs
    ("RPT_MATERIAL_APPROVAL", ctx(RPT, related=False, amounts_cr=[100]), NA),
    ("RPT_MATERIAL_APPROVAL", ctx(RPT, related=None, amounts_cr=[100]), INS),
    ("RPT_MATERIAL_APPROVAL", ctx(RPT, related=True), INS),
    ("RPT_MATERIAL_APPROVAL", ctx(RPT, related=True, amounts_cr=[100]), P),
    (
        "RPT_MATERIAL_APPROVAL",
        ctx(RPT, title="Ratification of RPTs", related=True, amounts_cr=[6000]),
        F,
    ),
    (
        "RPT_MATERIAL_APPROVAL",
        ctx(RPT, title="Ratification of RPTs", related=True, amounts_cr=[600], turnover_cr=1000),
        F,
    ),
    (
        "RPT_MATERIAL_APPROVAL",
        ctx(RPT, title="Ratification of RPTs", related=True, amounts_cr=[50], turnover_cr=1000),
        P,
    ),
    (
        "RPT_MATERIAL_APPROVAL",
        ctx(RPT, title="Ratification of RPTs", related=True, amounts_cr=[600]),
        INS,
    ),
    # RPT_OMNIBUS_VALIDITY: AGM -> next AGM (<= 15 months), other meetings <= 1 year
    ("RPT_OMNIBUS_VALIDITY", ctx(RPT, related=False, duration=3), NA),
    ("RPT_OMNIBUS_VALIDITY", ctx(RPT, related=True), INS),
    ("RPT_OMNIBUS_VALIDITY", ctx(RPT, related=True, duration=1.25), P),
    ("RPT_OMNIBUS_VALIDITY", ctx(RPT, related=True, duration=2), F),
    ("RPT_OMNIBUS_VALIDITY", ctx(RPT, related=True, duration=1.25, meeting=MeetingType.EGM), F),
    (
        "RPT_OMNIBUS_VALIDITY",
        ctx(RPT, related=True, duration=1.2, meeting=MeetingType.UNKNOWN),
        INS,
    ),
    ("RPT_OMNIBUS_VALIDITY", ctx(RPT, related=True, duration=1, meeting=MeetingType.UNKNOWN), P),
    # POL_RPT_NO_CAP
    ("POL_RPT_NO_CAP", ctx(RPT, related=False), NA),
    ("POL_RPT_NO_CAP", ctx(RPT, related=True, amounts_cr=[100]), P),
    ("POL_RPT_NO_CAP", ctx(RPT, related=True), F),
    ("POL_RPT_NO_CAP", ctx(RPT, related=None), F),
    # EXEC_PROMOTER_PAY_SPECIAL: above max(Rs 5 cr, 2.5% of net profit)
    ("EXEC_PROMOTER_PAY_SPECIAL", ctx(PAY, special=True), P),
    (
        "EXEC_PROMOTER_PAY_SPECIAL",
        ctx(PAY, persons=[person(is_promoter=False)], amounts_cr=[50]),
        NA,
    ),
    ("EXEC_PROMOTER_PAY_SPECIAL", ctx(PAY, persons=[person()], amounts_cr=[50]), INS),
    ("EXEC_PROMOTER_PAY_SPECIAL", ctx(PAY, persons=[person(is_promoter=True)]), INS),
    ("EXEC_PROMOTER_PAY_SPECIAL", ctx(PAY, persons=[person(is_promoter=True)], amounts_cr=[4]), P),
    (
        "EXEC_PROMOTER_PAY_SPECIAL",
        ctx(PAY, persons=[person(is_promoter=True)], amounts_cr=[8]),
        INS,
    ),
    (
        "EXEC_PROMOTER_PAY_SPECIAL",
        ctx(PAY, persons=[person(is_promoter=True)], amounts_cr=[8], net_profit_cr=100),
        F,
    ),
    (
        "EXEC_PROMOTER_PAY_SPECIAL",
        ctx(PAY, persons=[person(is_promoter=True)], amounts_cr=[8], net_profit_cr=400),
        P,
    ),
    (
        "EXEC_PROMOTER_PAY_SPECIAL",
        ctx(PAY, persons=[person(is_promoter=True, role="Non-Executive Chairman")], amounts_cr=[8]),
        NA,
    ),
    ("EXEC_PROMOTER_PAY_SPECIAL", ctx(PAY), INS),
    # POL_PAY_JUMP
    ("POL_PAY_JUMP", ctx(PAY), F),
    ("POL_PAY_JUMP", ctx(PAY, amounts_cr=[3]), INS),
    ("POL_PAY_JUMP", ctx(PAY, amounts_cr=[3], facts=["A 60% increase over last year."]), F),
    ("POL_PAY_JUMP", ctx(PAY, amounts_cr=[3], facts=["An increase of 20% over last year."]), P),
    # AUDITOR_ROTATION: individual 1 term, firm 2 terms of 5 years
    ("AUDITOR_ROTATION", ctx(AUD, duration=5), INS),
    ("AUDITOR_ROTATION", ctx(AUD, counterparty=FIRM), INS),
    ("AUDITOR_ROTATION", ctx(AUD, counterparty=FIRM, duration=10), F),
    ("AUDITOR_ROTATION", ctx(AUD, title="Appointment", counterparty=FIRM, duration=5), P),
    (
        "AUDITOR_ROTATION",
        ctx(AUD, persons=[person(name=FIRM, prior_tenure_years=5)], duration=5),
        P,
    ),
    (
        "AUDITOR_ROTATION",
        ctx(AUD, persons=[person(name=FIRM, prior_tenure_years=10)], duration=5),
        F,
    ),
    (
        "AUDITOR_ROTATION",
        ctx(AUD, persons=[person(name="Mr Ram Kumar", prior_tenure_years=5)], duration=5),
        F,
    ),
    ("AUDITOR_ROTATION", ctx(AUD, title="Re-appointment", counterparty=FIRM, duration=5), INS),
    # "second term" wording stands in for unstated prior years; a firm named only in the title
    (
        "AUDITOR_ROTATION",
        ctx(AUD, title=f"Re-appointment of {FIRM} for a second term", duration=5),
        P,
    ),
    (
        "AUDITOR_ROTATION",
        ctx(
            AUD,
            title="Re-appointment",
            counterparty=FIRM,
            duration=5,
            facts=["Third term of five years."],
        ),
        F,
    ),
    (
        "ID_TENURE_MAX",
        ctx(
            ID, title="Re-appointment for a second term", persons=[person(tenure_years_proposed=5)]
        ),
        P,
    ),
    (
        "ID_TENURE_MAX",
        ctx(ID, title="Re-appointment for a 3rd term", persons=[person(tenure_years_proposed=5)]),
        F,
    ),
]


@pytest.mark.parametrize(("rule_id", "context", "expected"), CASES)
def test_rule(rule_id: str, context: RuleContext, expected: RuleStatus) -> None:
    rule = RULES[rule_id]
    outcome = CHECKS[rule.check](rule, context)

    assert outcome.status == expected, outcome.detail
    assert outcome.detail


def test_every_rule_in_policy_is_tested_and_registered() -> None:
    assert {rule_id for rule_id, _, _ in CASES} == RULES.keys()
    assert {rule.check for rule in RULES.values()} == CHECKS.keys()


@pytest.mark.parametrize(
    ("turnover_cr", "threshold_cr"),
    [(10_000, 1_000), (30_000, 2_500), (100_000, 4_500), (200_000, 5_000)],
)
def test_schedule_xii_materiality_threshold(turnover_cr: float, threshold_cr: float) -> None:
    tiers = RULES["RPT_MATERIAL_APPROVAL"].params["materiality_tiers_inr_crore"]

    assert materiality_threshold_inr(turnover_cr * CR, tiers) == pytest.approx(threshold_cr * CR)


def test_evaluate_runs_only_rules_for_the_resolution_type() -> None:
    findings = evaluate(list(RULES.values()), ctx(ID, special=True, persons=[person(age=50)]))

    assert [f.rule_id for f in findings] == [
        "ID_TENURE_MAX",
        "ID_SPECIAL_RESOLUTION",
        "NED_AGE_75_SPECIAL",
        "DIRECTOR_PERIODIC_APPROVAL",
        "POL_ATTENDANCE_MIN",
    ]
    assert {f.kind for f in findings} == {RuleKind.LAW, RuleKind.POLICY}
    assert evaluate(list(RULES.values()), ctx(ResolutionType.DIVIDEND)) == []


def test_load_policy_rejects_unknown_checks(tmp_path: Path) -> None:
    rule = RULES["ID_SPECIAL_RESOLUTION"].model_dump(mode="json") | {"check": "nope"}
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump({"rules": [rule]}), encoding="utf-8")

    with pytest.raises(PolicyError, match="nope"):
        load_policy(path)


def test_rule_spec_round_trips() -> None:
    rule = RULES["AUDITOR_ROTATION"]
    assert RuleSpec.model_validate(rule.model_dump()) == rule
