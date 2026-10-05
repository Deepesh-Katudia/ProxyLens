import json
from pathlib import Path
from typing import Any

import pytest

from app.dataset.jsonl import write_jsonl
from app.schemas.resolution import Money, Person, ResolutionExtraction
from eval.figures import confusion_svg
from eval.metrics import (
    INVALID,
    amounts_prf,
    counterparty_prf,
    macro_f1,
    persons_prf,
    score_run,
    special_prf,
)
from eval.predictions import PredictionItem, PredictionRun, load_runs, save_run
from eval.reference import load_reference
from eval.report import render


def ext(**kwargs: Any) -> ResolutionExtraction:
    base: dict[str, Any] = {
        "item_no": 1,
        "title": "t",
        "resolution_type": "DIVIDEND",
        "is_special_resolution": False,
    }
    return ResolutionExtraction.model_validate(base | kwargs)


def test_person_names_match_without_honorifics_or_punctuation() -> None:
    pred = [Person(name="Mr. A. K. Rao"), Person(name="Ms Priya Shah")]
    ref = [Person(name="A K Rao"), Person(name="Dr. Vijay Menon")]

    prf = persons_prf(pred, ref)

    assert (prf.tp, prf.fp, prf.fn) == (1, 1, 1)
    assert prf.f1 == pytest.approx(0.5)


def test_amounts_match_within_one_percent_one_to_one() -> None:
    pred = [Money(amount_inr=50_400_000, raw="x"), Money(amount_inr=50_400_000, raw="y")]
    ref = [Money(amount_inr=50_000_000, raw="Rs 5 crore")]

    prf = amounts_prf(pred, ref)

    assert (prf.tp, prf.fp, prf.fn) == (1, 1, 0)
    assert amounts_prf([Money(amount_inr=51_000_000, raw="x")], ref).tp == 0  # 2% off


def test_special_and_counterparty() -> None:
    truth = ext(is_special_resolution=True, counterparty="XYZ Logistics Private Limited")
    pred = ext(is_special_resolution=True, counterparty="XYZ Logistics Pvt. Ltd.")

    assert special_prf(pred, truth).f1 == 1.0
    assert special_prf(None, truth).fn == 1  # invalid reply misses a true special
    assert counterparty_prf(pred, truth).tp == 1
    assert counterparty_prf(ext(), ext()).tp + counterparty_prf(ext(), ext()).fn == 0


def test_macro_f1_counts_invalid_as_a_miss() -> None:
    perfect = [("DIVIDEND", "DIVIDEND"), ("ESOP", "ESOP")]
    half = [("DIVIDEND", "DIVIDEND"), ("ESOP", INVALID)]

    assert macro_f1(perfect) == 1.0
    assert macro_f1(half) == pytest.approx(0.5)


def run_of(items: list[PredictionItem], provider: str = "teacher") -> PredictionRun:
    return PredictionRun(
        run_id=f"r-{provider}",
        provider=provider,
        model="m",
        split="test",
        created_at="2026-10-05T00:00:00+00:00",
        items=items,
    )


def test_score_run_counts_invalid_replies_as_wrong() -> None:
    reference = {"a": ext(), "b": ext(resolution_type="ESOP"), "c": ext()}
    items = [
        PredictionItem(item_id="a", output_text=ext().model_dump_json(), latency_ms=1000,
                       valid_after_repair=True, cost_usd=0.001),
        PredictionItem(item_id="b", output_text="{oops", latency_ms=3000,
                       valid_after_repair=False, cost_usd=0.002),
        PredictionItem(item_id="zzz", output_text="ignored: no reference"),
    ]  # fmt: skip

    m = score_run(run_of(items), reference)

    assert m.n == 2
    assert m.json_valid == 0.5 and m.type_accuracy == 0.5
    assert m.fallback_rate == 0.5
    assert m.cost_usd_total == pytest.approx(0.003)
    assert m.confusion == {"DIVIDEND": {"DIVIDEND": 1}, "ESOP": {INVALID: 1}}
    assert "INVALID" in confusion_svg(m.confusion, "t").replace("invalid", "INVALID")


def test_notebook_runs_have_no_fallback_rate() -> None:
    items = [PredictionItem(item_id="a", output_text=ext().model_dump_json())]

    assert score_run(run_of(items, "base_hf"), {"a": ext()}).fallback_rate is None


def test_load_runs_keeps_the_newest_per_model(tmp_path: Path) -> None:
    old = run_of([]).model_copy(update={"run_id": "old"})
    new = old.model_copy(update={"run_id": "new", "created_at": "2026-10-06T00:00:00+00:00"})
    save_run(old, tmp_path)
    save_run(new, tmp_path)

    assert [r.run_id for r in load_runs(tmp_path)] == ["new"]


def write_reference(
    tmp_path: Path, labels: list[dict[str, Any]], drafts: list[dict[str, Any]]
) -> Any:
    write_jsonl(tmp_path / "labels.jsonl", labels)
    write_jsonl(tmp_path / "drafts.jsonl", drafts)
    return load_reference(tmp_path / "labels.jsonl", tmp_path / "drafts.jsonl")


def label(
    item_id: str, extraction: ResolutionExtraction, draft_model: str | None
) -> dict[str, Any]:
    payload = {"status": "labelled", "extraction": extraction.model_dump(mode="json"),
               "labeller": "x", "draft_model": draft_model}  # fmt: skip
    return {"item_id": item_id, "label": payload}


def test_reference_provenance_is_derived_from_the_data(tmp_path: Path) -> None:
    drafted = ext(title="drafted")
    drafts = [{"item_id": i, "model": "anthropic/claude-sonnet-5.5",
               "extraction": drafted.model_dump(mode="json")} for i in "abc"]  # fmt: skip

    unedited = write_reference(
        tmp_path, [label(i, drafted, "anthropic/claude-sonnet-5.5") for i in "ab"], drafts
    )
    edited = write_reference(
        tmp_path, [label("a", ext(title="fixed"), "anthropic/claude-sonnet-5.5")], drafts
    )
    by_hand = write_reference(tmp_path, [label("z", ext(), None)], drafts)

    assert unedited.kind == "model" and "not human gold" in unedited.describe()
    assert edited.kind == "human" and edited.edited_drafts == 1
    assert by_hand.kind == "human" and by_hand.from_blank == 1


def test_report_states_the_reference_kind(tmp_path: Path) -> None:
    drafted = ext()
    drafts = [{"item_id": "a", "model": "claude", "extraction": drafted.model_dump(mode="json")}]
    reference = write_reference(tmp_path, [label("a", drafted, "claude")], drafts)
    reply = json.dumps(drafted.model_dump(mode="json"))
    item = PredictionItem(
        item_id="a", output_text=reply, cost_usd=0.001, latency_ms=900, valid_after_repair=True
    )
    run = run_of([item])

    text = render(reference, [(score_run(run, reference.labels), run)], None)

    assert "Model-labelled reference" in text
    assert "agreement with that model" in text
    assert "| 100.0% | 100.0% |" in text
