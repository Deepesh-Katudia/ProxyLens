# Evaluation

Predictions and metrics are kept separate. Anything that generates outputs (the
Colab notebook `02_eval_student`, or the local harness for GGUF/teacher runs)
writes **raw predictions**. Metrics are computed in this repo from those files
and the gold labels (Phase 7), so every provider is scored the same way and the
gold labels never leave the machine.

## Prediction file format: `eval/results/<run_id>.json`

```json
{
  "run_id": "2026-10-20_finetuned_lora_test",
  "provider": "base_hf | finetuned_lora | local_gguf | teacher",
  "model": "unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
  "split": "test | val",
  "created_at": "2026-10-20T11:02:13+00:00",
  "hardware": "Tesla T4",
  "decoding": {"greedy": true, "max_new_tokens": 1024, "constrained": false},
  "items": [
    {"item_id": "682bb8696d21-3", "output_text": "{...}", "latency_ms": 8123, "output_tokens": 241}
  ]
}
```

- `item_id` matches `data/gold/candidates.jsonl` (test) or `val-<index>` in `data/sft/val.jsonl` order (val).
- `output_text` is the model's raw reply before any repair, so JSON validity is measured as SPEC 8 defines it.
- `constrained` records whether decoding was grammar-constrained to the schema (llama.cpp can; the
  notebooks don't), since that changes what validity means.
