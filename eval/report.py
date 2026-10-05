"""Score every prediction run against the reference and write eval/REPORT.md.

    uv run python -m eval.report [--db]

Writes eval/REPORT.md and eval/figures/confusion_<run>.svg. With --db it also
stores the summary in `eval_runs` (what the /eval page shows) and measures
citation precision from the analyses saved by the web app.
"""

import argparse
import asyncio
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.dataset.jsonl import read_jsonl
from app.db.client import create_client
from app.db.collections import ANALYSES, EVAL_RUNS
from app.gold.store import DEFAULT_CANDIDATES
from eval.figures import confusion_svg
from eval.metrics import RunMetrics, score_run
from eval.predictions import PredictionRun, load_runs
from eval.reference import ReferenceSet, load_reference

REPORT = Path("eval/REPORT.md")
FIGURES = Path("eval/figures")
FAILURE_CASES = 5
# Cloud Run (request-based billing, tier 1), for the student's cost estimate from latency.
CLOUD_RUN_VCPU_S_USD = 0.000024
CLOUD_RUN_GIB_S_USD = 0.0000025
SERVING_VCPU, SERVING_GIB = 4, 8  # SPEC 4 serving config
STUDENT_PROVIDERS = ("finetuned_gguf", "local_gguf", "finetuned_lora")
_DROPPED = re.compile(r"Dropped (\d+) citation")
CPU_ESTIMATE = "estimate: local p50 latency x Cloud Run price"
RETRIEVAL_NOTE = (
    "- Retrieval recall@6: 1.00 on 20 hand-written queries (`scripts/eval_retrieval.py`, Phase 1)."
)

DISPLAY = {
    "base_hf": "Base Qwen2.5-3B, zero-shot (GPU)",
    "base_gguf": "Base Qwen2.5-3B, zero-shot (GGUF, CPU)",
    "finetuned_lora": "Fine-tuned Qwen2.5-3B (LoRA, GPU)",
    "finetuned_gguf": "Fine-tuned Qwen2.5-3B (GGUF Q4_K_M, CPU)",
    "local_gguf": "Fine-tuned Qwen2.5-3B (GGUF Q4_K_M, CPU)",
    "teacher": "Teacher",
    "openrouter": "Untuned",
}


def display_name(m: RunMetrics, run: PredictionRun | None = None) -> str:
    base = DISPLAY.get(m.provider, m.provider)
    name = f"{base} ({m.model})" if m.provider in ("teacher", "openrouter") else base
    # Grammar-constrained decoding makes JSON validity ~100% by construction: say so.
    return f"{name}, JSON grammar" if run is not None and run.decoding.constrained else name


def cost_per_1k(m: RunMetrics, run: PredictionRun) -> tuple[float | None, str]:
    if m.cost_usd_total is not None:
        return m.cost_usd_total / m.n * 1000, "API usage"
    if "CPU" in run.hardware and m.latency_p50_ms:
        per_second = SERVING_VCPU * CLOUD_RUN_VCPU_S_USD + SERVING_GIB * CLOUD_RUN_GIB_S_USD
        return m.latency_p50_ms / 1000 * per_second * 1000, CPU_ESTIMATE
    return None, ""


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def seconds(ms: float | None) -> str:
    return "—" if ms is None else f"{ms / 1000:.1f} s"


def metrics_table(scored: list[tuple[RunMetrics, PredictionRun]]) -> list[str]:
    lines = [
        "| Model | n | JSON valid | Type acc. | Type macro-F1 | Persons F1 | Amounts F1 | "
        "Special F1 | Counterparty F1 | Fallback | Latency p50 / p95 | Cost / 1k |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m, run in scored:
        cost, _ = cost_per_1k(m, run)
        lines.append(
            f"| {display_name(m, run)} | {m.n} | {pct(m.json_valid)} | {pct(m.type_accuracy)} | "
            f"{pct(m.type_macro_f1)} | {pct(m.persons_f1)} | {pct(m.amounts_f1)} | "
            f"{pct(m.special_f1)} | {pct(m.counterparty_f1)} | {pct(m.fallback_rate)} | "
            f"{seconds(m.latency_p50_ms)} / {seconds(m.latency_p95_ms)} | "
            f"{'—' if cost is None else f'${cost:,.2f}'} |"
        )
    return lines


def subset_note(scored: list[tuple[RunMetrics, PredictionRun]]) -> list[str]:
    sizes = {m.n for m, _ in scored}
    if len(sizes) <= 1:
        return []
    full = max(sizes)
    partial = ", ".join(f"{display_name(m, run)} (n={m.n})" for m, run in scored if m.n < full)
    return [
        f"**Not all rows cover the same items.** {partial} was scored on the first items of the "
        f"{full}-item set only, so compare it with care. F1 shows — where the items contain "
        "nothing of that kind.",
        "",
    ]


def failure_cases(m: RunMetrics, run: PredictionRun) -> list[str]:
    rows = read_jsonl(DEFAULT_CANDIDATES) if DEFAULT_CANDIDATES.exists() else []
    candidates = {c["item_id"]: c for c in rows}
    outputs = {i.item_id: i.output_text for i in run.items}
    misses = [s for s in m.items if not s.type_ok][:FAILURE_CASES]
    lines = [f"### Failure cases: {display_name(m, run)}", ""]
    if not misses:
        return [*lines, "No resolution-type errors on this set.", ""]
    for s in misses:
        c = candidates.get(s.item_id, {})
        text = " ".join(str(c.get("text", "")).split())[:240]
        what = (
            "Reply was not valid JSON for the schema."
            if not s.valid
            else f"Predicted **{s.predicted_type}**, reference **{s.reference_type}**."
        )
        lines += [
            f"- **{c.get('company', '?')}**, item {c.get('item_no', '?')} (`{s.item_id}`): {what}",
            f"  > {text}…",
        ]
        if not s.valid:
            lines.append(f"  Output started: `{outputs.get(s.item_id, '')[:120]!r}`")
    return [*lines, ""]


def render(
    reference: ReferenceSet,
    scored: list[tuple[RunMetrics, PredictionRun]],
    citation: dict[str, Any] | None,
) -> str:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# ProxyLens evaluation report",
        "",
        f"_Generated {stamp} by `python -m eval.report`. Do not edit by hand._",
        "",
        "## Reference labels",
        "",
        f"**{reference.describe()}**",
        "",
        "Scores below measure agreement with this reference. "
        + (
            "Because most labels are an independent model's, read them as agreement with "
            "that model, not as accuracy against human judgement."
            if reference.kind != "human"
            else "Labels were written by hand on the /label page."
        ),
        "",
        "## Extraction (company-held-out test split)",
        "",
        *metrics_table(scored),
        "",
        *subset_note(scored),
        "JSON valid is measured on the first reply, before any repair. Fallback is the share "
        "still invalid after one repair, i.e. sent to the teacher (only measured by "
        "`eval.run`; notebook runs show —). Invalid replies count as wrong in every other "
        "column.",
        "",
    ]
    for m, run in scored:
        _, basis = cost_per_1k(m, run)
        if basis.startswith("estimate"):
            serving = f"{SERVING_VCPU} vCPU / {SERVING_GIB} GiB"
            lines.append(f"- {display_name(m, run)} cost: {basis} ({serving}).")
    lines += ["", "## Confusion matrices", ""]
    for m, run in scored:
        lines.append(f"![{display_name(m, run)}](figures/confusion_{run.run_id}.svg)")
    lines += ["", "## Decision pipeline", ""]
    if citation:
        lines.append(
            f"- Citation precision before guardrails: **{pct(citation['precision'])}** "
            f"({citation['kept']} kept of {citation['kept'] + citation['dropped']} cited, "
            f"over {citation['analyses']} analyses saved by the web app). Every citation shown "
            "to users passes the check by construction."
        )
    else:
        lines.append("- Citation precision: run `python -m eval.report --db` to measure it.")
    lines += [
        RETRIEVAL_NOTE,
        "- Recommendation agreement: not measured; the reference set has no vote labels.",
        "",
        "## Failure cases",
        "",
    ]
    students = [(m, r) for m, r in scored if m.provider in STUDENT_PROVIDERS] or scored[:1]
    for m, run in students[:1]:
        lines += failure_cases(m, run)
    return "\n".join(lines) + "\n"


async def citation_precision() -> dict[str, Any] | None:
    settings = get_settings()
    client = create_client(settings)
    if client is None:
        return None
    try:
        kept = dropped = analyses = 0
        cursor = client[settings.mongodb_db][ANALYSES].find({}, {"citations": 1, "adjustments": 1})
        async for doc in cursor:
            analyses += 1
            kept += len(doc.get("citations", []))
            for note in doc.get("adjustments", []):
                if match := _DROPPED.search(note):
                    dropped += int(match.group(1))
        total = kept + dropped
        return {"analyses": analyses, "kept": kept, "dropped": dropped,
                "precision": kept / total if total else None}  # fmt: skip
    finally:
        await client.close()


async def store_summary(summary: dict[str, Any]) -> None:
    settings = get_settings()
    client = create_client(settings)
    if client is None:
        raise SystemExit("--db needs MONGODB_URI")
    try:
        await client[settings.mongodb_db][EVAL_RUNS].insert_one(summary)
    finally:
        await client.close()


def summary_doc(
    reference: ReferenceSet,
    scored: list[tuple[RunMetrics, PredictionRun]],
    citation: dict[str, Any] | None,
) -> dict[str, Any]:
    providers = []
    for m, run in scored:
        cost, basis = cost_per_1k(m, run)
        providers.append(
            {
                "name": display_name(m, run), "provider": m.provider, "model": m.model, "n": m.n,
                "run_id": run.run_id, "hardware": run.hardware,
                "metrics": {
                    "json_valid": m.json_valid, "fallback_rate": m.fallback_rate,
                    "type_accuracy": m.type_accuracy, "type_macro_f1": m.type_macro_f1,
                    "persons_f1": m.persons_f1, "amounts_f1": m.amounts_f1,
                    "special_f1": m.special_f1, "counterparty_f1": m.counterparty_f1,
                    "latency_p50_ms": m.latency_p50_ms, "latency_p95_ms": m.latency_p95_ms,
                    "cost_per_1k_usd": cost, "cost_basis": basis,
                },
                "confusion": m.confusion,
            }
        )  # fmt: skip
    return {
        "run_id": datetime.now(UTC).strftime("%Y-%m-%dT%H%M_report"),
        "split": "test",
        "created_at": datetime.now(UTC),
        "reference": reference.as_dict(),
        "providers": providers,
        "citation_precision": citation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", action="store_true", help="store in eval_runs; measure citations")
    args = parser.parse_args(argv)

    reference = load_reference()
    if not reference.labels:
        raise SystemExit("no reference labels in data/gold/labels.jsonl")
    runs = load_runs()
    if not runs:
        raise SystemExit("no prediction runs in eval/results/")
    scored = [(score_run(run, reference.labels), run) for run in runs]
    scored.sort(key=lambda pair: -pair[0].type_macro_f1)
    citation = asyncio.run(citation_precision()) if args.db else None

    FIGURES.mkdir(parents=True, exist_ok=True)
    for m, run in scored:
        svg = confusion_svg(m.confusion, f"{display_name(m, run)}: resolution type")
        (FIGURES / f"confusion_{run.run_id}.svg").write_text(svg, encoding="utf-8")
    REPORT.write_text(render(reference, scored, citation), encoding="utf-8")
    print(f"wrote {REPORT} ({len(scored)} runs)")
    if args.db:
        asyncio.run(store_summary(summary_doc(reference, scored, citation)))
        print("stored summary in eval_runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
