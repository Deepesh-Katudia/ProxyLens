"""Load config/policy.yaml and evaluate its rules against an extraction (SPEC 6.1)."""

from collections.abc import Callable
from pathlib import Path

import yaml

from app.rules import auditors, directors, remuneration, transactions
from app.rules.models import CheckResult, RuleContext, RuleFinding, RuleSpec

DEFAULT_POLICY_PATH = Path("config/policy.yaml")

Check = Callable[[RuleSpec, RuleContext], CheckResult]

CHECKS: dict[str, Check] = {
    "id_tenure_max": directors.id_tenure_max,
    "id_special_resolution": directors.id_special_resolution,
    "ned_age_special": directors.ned_age_special,
    "director_periodic_approval": directors.director_periodic_approval,
    "attendance_min": directors.attendance_min,
    "rpt_material_approval": transactions.rpt_material_approval,
    "rpt_omnibus_validity": transactions.rpt_omnibus_validity,
    "rpt_no_cap": transactions.rpt_no_cap,
    "exec_promoter_pay_special": remuneration.exec_promoter_pay_special,
    "pay_jump": remuneration.pay_jump,
    "auditor_rotation": auditors.auditor_rotation,
}


class PolicyError(ValueError):
    """policy.yaml is malformed or names a check that does not exist."""


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> list[RuleSpec]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = [RuleSpec.model_validate(raw) for raw in data["rules"]]
    unknown = sorted({r.check for r in rules} - CHECKS.keys())
    if unknown:
        raise PolicyError(f"policy.yaml names unknown checks: {', '.join(unknown)}")
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        raise PolicyError("policy.yaml has duplicate rule ids")
    return rules


def applicable_rules(rules: list[RuleSpec], context: RuleContext) -> list[RuleSpec]:
    resolution_type = context.extraction.resolution_type
    return [rule for rule in rules if resolution_type in rule.applies_to]


def evaluate(rules: list[RuleSpec], context: RuleContext) -> list[RuleFinding]:
    """Findings for every rule that applies to the resolution's type, in policy order."""
    findings = []
    for rule in applicable_rules(rules, context):
        outcome = CHECKS[rule.check](rule, context)
        findings.append(
            RuleFinding(
                rule_id=rule.id,
                kind=rule.kind,
                status=outcome.status,
                detail=outcome.detail,
                citation=rule.citation,
                source_url=rule.source_url,
                verified=rule.verified,
            )
        )
    return findings
