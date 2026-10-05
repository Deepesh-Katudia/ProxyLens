"""Store the fine-tuned model's scores on a fixed item subset as the regression baseline.

    uv run python -m eval.baseline [--run-id RUN]   # default: newest finetuned_gguf run

Writes eval/baseline.json (item ids and two scores; no labels). The test in
tests/test_eval_regression.py re-runs the model on those items and fails if JSON
validity or type macro-F1 drops more than 2 points below it.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from eval.metrics import score_run
from eval.predictions import load_runs
from eval.reference import load_reference

BASELINE = Path("eval/baseline.json")
STUDENT = "finetuned_gguf"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)

    runs = [
        r
        for r in load_runs()
        if (r.run_id == args.run_id if args.run_id else r.provider == STUDENT)
    ]
    if not runs:
        raise SystemExit("no matching run in eval/results/")
    run = runs[-1]
    reference = load_reference()
    metrics = score_run(run, reference.labels)
    baseline = {
        "run_id": run.run_id,
        "model": run.model,
        "constrained": run.decoding.constrained,
        "reference_kind": reference.kind,
        "item_ids": [s.item_id for s in metrics.items],
        "json_valid": metrics.json_valid,
        "type_macro_f1": metrics.type_macro_f1,
        "created_at": datetime.now(UTC).isoformat(),
    }
    BASELINE.write_text(json.dumps(baseline, indent=1) + "\n", encoding="utf-8")
    print(
        f"wrote {BASELINE}: {metrics.n} items, json_valid "
        f"{metrics.json_valid:.3f}, type macro-F1 {metrics.type_macro_f1:.3f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
