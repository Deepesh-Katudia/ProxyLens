from pathlib import Path
from typing import Any

import pytest
import yaml

from app.schemas.resolution import ResolutionType

REQUIRED = {"id", "applies_to", "kind", "check", "params", "citation", "source_url", "as_of"}


@pytest.fixture(scope="module")
def rules() -> list[dict[str, Any]]:
    data = yaml.safe_load(Path("config/policy.yaml").read_text(encoding="utf-8"))
    return list(data["rules"])


def test_every_rule_has_required_fields(rules: list[dict[str, Any]]) -> None:
    for rule in rules:
        assert rule.keys() >= REQUIRED, rule["id"]
        assert rule["kind"] in {"LAW", "POLICY"}
        assert all(ResolutionType(t) for t in rule["applies_to"])


def test_rule_ids_are_unique(rules: list[dict[str, Any]]) -> None:
    ids = [rule["id"] for rule in rules]
    assert len(ids) == len(set(ids))


def test_verified_law_rules_record_source_and_date(rules: list[dict[str, Any]]) -> None:
    for rule in rules:
        if rule["kind"] == "LAW" and rule["verified"]:
            assert str(rule["source_url"]).startswith("https://"), rule["id"]
            assert rule["as_of"], rule["id"]
