# Evaluation

Predictions and metrics are kept separate. Anything that generates outputs (the
Colab notebook `02_eval_student`, or `eval.run` for API and local GGUF models)
writes **raw predictions**. Metrics are computed in this repo from those files
and the reference labels, so every provider is scored the same way and the
labels never leave the machine.

```bash
uv run python -m eval.run --provider teacher                       # OpenRouter teacher
uv run python -m eval.run --provider openrouter --model qwen/qwen-2.5-7b-instruct
uv run python -m eval.run --provider gguf --name finetuned_gguf    # local CPU, ~1 min/item
uv run python -m eval.report --db    # eval/REPORT.md + figures; summary to eval_runs (/eval page)
uv run python -m eval.baseline       # regression baseline from the newest finetuned_gguf run
PROXYLENS_MODEL_TESTS=1 uv run pytest tests/test_eval_regression.py   # opt-in, slow
```

Base and fine-tuned 3B on a GPU: run `notebooks/02_eval_student.ipynb` on Colab
(T4) and copy the two downloaded JSON files into `eval/results/`.

## Reference labels

`data/gold/labels.jsonl` (local only). The report derives their provenance from
the data instead of asserting it: a label saved unchanged from its model draft
(`scripts/draft_gold.py`) counts as model-labelled; a label typed on a blank form,
or a draft that was edited, counts as human. REPORT.md and the /eval page state
the result (human, model or mixed) above every score.

## Prediction file format: `eval/results/<run_id>.json`

```json
{
  "run_id": "2026-10-20_finetuned_lora_test",
  "provider": "base_hf | finetuned_lora | finetuned_gguf | teacher | openrouter",
  "model": "unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
  "split": "test | val",
  "created_at": "2026-10-20T11:02:13+00:00",
  "hardware": "Tesla T4",
  "decoding": {"greedy": true, "max_new_tokens": 1024, "constrained": false},
  "items": [
    {"item_id": "682bb8696d21-3", "output_text": "{...}", "latency_ms": 8123, "output_tokens": 241,
     "valid_after_repair": true, "cost_usd": 0.0011}
  ]
}
```

- `item_id` matches `data/gold/candidates.jsonl` (test) or `val-<index>` in `data/sft/val.jsonl` order (val).
- `output_text` is the model's raw first reply before any repair, so JSON validity is measured as SPEC 8 defines it.
- `valid_after_repair` and `cost_usd` are written by `eval.run` only (the notebook does no repair); the fallback rate is reported only where it was measured.
- `constrained` records whether decoding was grammar-constrained to the schema (llama.cpp can; the
  notebooks don't), since that changes what validity means.
