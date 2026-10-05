"""Extraction metrics against the reference labels (SPEC 8).

Every metric is computed over the items that have a reference label. A reply that
is not valid JSON for the schema counts as a wrong answer everywhere (its type is
`INVALID` in the confusion matrix), so validity failures are never hidden.
"""

import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.llm.extraction import validate
from app.schemas.resolution import Money, Person, ResolutionExtraction, ResolutionType
from eval.predictions import PredictionRun

INVALID = "INVALID"
AMOUNT_TOLERANCE = 0.01  # SPEC 8: amounts match within +-1%
_HONORIFIC = re.compile(r"^(mr|mrs|ms|dr|shri|smt|smt\.|kum|prof|ca|cs)\.?\s+", re.IGNORECASE)
_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_COMPANY_SUFFIX = re.compile(r"\b(private|pvt|limited|ltd|llp|inc|plc)\b")


@dataclass(frozen=True)
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def __add__(self, other: "PRF") -> "PRF":
        return PRF(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def scored(self) -> float | None:
        """F1, or None when there was nothing to find and nothing was predicted."""
        return None if self.tp + self.fp + self.fn == 0 else self.f1

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class ItemScore:
    item_id: str
    valid: bool
    reference_type: str
    predicted_type: str
    type_ok: bool


@dataclass
class RunMetrics:
    provider: str
    model: str
    n: int
    json_valid: float
    fallback_rate: float | None  # None when the run did not attempt a repair
    type_accuracy: float
    type_macro_f1: float
    persons_f1: float | None  # None: no positives in reference or predictions
    amounts_f1: float | None
    special_f1: float | None
    counterparty_f1: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    cost_usd_total: float | None
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    items: list[ItemScore] = field(default_factory=list)


def parse(text: str) -> ResolutionExtraction | None:
    try:
        return validate(text)
    except ValueError:
        return None


def normalise_name(name: str) -> str:
    text = _HONORIFIC.sub("", name.strip().lower())
    return " ".join(_NON_WORD.sub(" ", text).split())


def normalise_party(name: str) -> str:
    text = _NON_WORD.sub(" ", name.lower())
    return " ".join(_COMPANY_SUFFIX.sub(" ", text).split())


def persons_prf(predicted: list[Person], reference: list[Person]) -> PRF:
    pred = {normalise_name(p.name) for p in predicted if p.name.strip()}
    ref = {normalise_name(p.name) for p in reference if p.name.strip()}
    hits = len(pred & ref)
    return PRF(hits, len(pred) - hits, len(ref) - hits)


def amounts_prf(predicted: list[Money], reference: list[Money]) -> PRF:
    """Greedy one-to-one match of rupee values within +-1%."""
    pred = [m.amount_inr for m in predicted if m.amount_inr is not None]
    ref = [m.amount_inr for m in reference if m.amount_inr is not None]
    unmatched = list(ref)
    hits = 0
    for value in pred:
        match = next(
            (r for r in unmatched if abs(value - r) <= AMOUNT_TOLERANCE * max(abs(r), 1.0)), None
        )
        if match is not None:
            unmatched.remove(match)
            hits += 1
    return PRF(hits, len(pred) - hits, len(unmatched))


def special_prf(predicted: ResolutionExtraction | None, reference: ResolutionExtraction) -> PRF:
    """F1 of the 'special resolution' class; an invalid reply misses a true special."""
    said = predicted is not None and predicted.is_special_resolution
    truth = reference.is_special_resolution
    return PRF(int(said and truth), int(said and not truth), int(truth and not said))


def counterparty_prf(
    predicted: ResolutionExtraction | None, reference: ResolutionExtraction
) -> PRF:
    pred = normalise_party(predicted.counterparty) if predicted and predicted.counterparty else ""
    ref = normalise_party(reference.counterparty) if reference.counterparty else ""
    if not pred and not ref:
        return PRF()
    hit = bool(pred and ref and (pred in ref or ref in pred))
    return PRF(int(hit), int(bool(pred) and not hit), int(bool(ref) and not hit))


def macro_f1(pairs: Iterable[tuple[str, str]]) -> float:
    """Macro-F1 over the reference classes (INVALID predictions count as misses)."""
    pairs = list(pairs)
    classes = sorted({ref for ref, _ in pairs})
    scores = []
    for c in classes:
        tp = sum(1 for r, p in pairs if r == c and p == c)
        fp = sum(1 for r, p in pairs if r != c and p == c)
        fn = sum(1 for r, p in pairs if r == c and p != c)
        scores.append(PRF(tp, fp, fn).f1)
    return statistics.fmean(scores) if scores else 0.0


def _percentile(values: list[int], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return float(ordered[index])


def score_run(run: PredictionRun, reference: dict[str, ResolutionExtraction]) -> RunMetrics:
    predictions = {item.item_id: item for item in run.items if item.item_id in reference}
    if not predictions:
        raise ValueError(f"{run.run_id}: no predictions overlap the reference labels")
    persons = amounts = special = counterparty = PRF()
    scores: list[ItemScore] = []
    confusion: dict[str, dict[str, int]] = {}
    for item_id, prediction in predictions.items():
        ref = reference[item_id]
        pred = parse(prediction.output_text)
        predicted_type = pred.resolution_type.value if pred else INVALID
        scores.append(
            ItemScore(
                item_id=item_id,
                valid=pred is not None,
                reference_type=ref.resolution_type.value,
                predicted_type=predicted_type,
                type_ok=predicted_type == ref.resolution_type.value,
            )
        )
        row = confusion.setdefault(ref.resolution_type.value, {})
        row[predicted_type] = row.get(predicted_type, 0) + 1
        persons += persons_prf(pred.persons if pred else [], ref.persons)
        amounts += amounts_prf(pred.amounts if pred else [], ref.amounts)
        special += special_prf(pred, ref)
        counterparty += counterparty_prf(pred, ref)

    n = len(scores)
    repairs = [p.valid_after_repair for p in predictions.values()]
    repaired = all(r is not None for r in repairs)  # eval.run repairs; notebook 02 does not
    costs = [p.cost_usd for p in predictions.values() if p.cost_usd is not None]
    latencies = [p.latency_ms for p in predictions.values() if p.latency_ms > 0]
    return RunMetrics(
        provider=run.provider,
        model=run.model,
        n=n,
        json_valid=sum(s.valid for s in scores) / n,
        fallback_rate=sum(1 for r in repairs if r is False) / n if repaired else None,
        type_accuracy=sum(s.type_ok for s in scores) / n,
        type_macro_f1=macro_f1((s.reference_type, s.predicted_type) for s in scores),
        persons_f1=persons.scored,
        amounts_f1=amounts.scored,
        special_f1=special.scored,
        counterparty_f1=counterparty.scored,
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        cost_usd_total=sum(costs) if len(costs) == n else None,
        confusion=confusion,
        items=scores,
    )


TYPE_ORDER = [t.value for t in ResolutionType]
