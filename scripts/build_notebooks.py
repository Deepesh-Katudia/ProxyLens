"""Generate the Colab notebooks in notebooks/ (SPEC 7.3-7.4).

    uv run python -m scripts.build_notebooks

The notebooks are generated rather than hand-edited so their validation schema
is copied from app/schemas/resolution.py and cannot drift from the repo.
"""

import json
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

NOTEBOOKS = Path("notebooks")
SCHEMA_SOURCE = Path("app/schemas/resolution.py")

Cell = tuple[str, str]  # (cell_type, source)


def md(text: str) -> Cell:
    return ("markdown", dedent(text).strip())


def code(text: str) -> Cell:
    return ("code", dedent(text).strip())


def notebook(cells: list[Cell]) -> dict[str, Any]:
    def as_cell(kind: str, source: str) -> dict[str, Any]:
        lines = source.splitlines(keepends=True)
        cell: dict[str, Any] = {"cell_type": kind, "metadata": {}, "source": lines}
        if kind == "code":
            cell |= {"execution_count": None, "outputs": []}
        return cell

    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"gpuType": "T4", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "cells": [as_cell(kind, source) for kind, source in cells],
    }


# --- shared cells ------------------------------------------------------------

INSTALL = code(
    """
    %%capture
    # Unsloth pulls matching torch / transformers / trl / peft / bitsandbytes for Colab.
    !pip install -q unsloth
    !pip install -q "huggingface_hub>=0.25" "pydantic>=2.8"
    """
)

SETUP = code(
    """
    from unsloth import FastLanguageModel  # import first: Unsloth patches transformers/trl

    import glob, json, os, time
    import torch
    from google.colab import drive, userdata
    from huggingface_hub import HfApi, snapshot_download

    print("torch", torch.__version__, "| GPU:", torch.cuda.get_device_name(0))

    HF_TOKEN = userdata.get("HF_TOKEN")  # Colab secret; needs write access
    HF_USER = HfApi(token=HF_TOKEN).whoami()["name"]
    DATASET_REPO = f"{HF_USER}/proxylens-sft-v1"           # pushed by scripts/push_sft_to_hub.py
    LORA_REPO = f"{HF_USER}/proxylens-qwen3b-lora-v1"
    GGUF_REPO = f"{HF_USER}/proxylens-qwen3b-gguf-v1"
    GGUF_FILE = "proxylens-q4_k_m.gguf"                     # = STUDENT_GGUF_FILE in .env
    BASE_MODEL = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit"
    MAX_SEQ_LEN = 4096        # longest SFT example is ~4.1k tokens
    MAX_NEW_TOKENS = 1024     # longest teacher answer is ~870 tokens
    SEED = 3407
    print("HF user:", HF_USER)
    """
)


def schema_cell() -> Cell:
    """The repo's ResolutionExtraction schema, copied verbatim."""
    source = SCHEMA_SOURCE.read_text(encoding="utf-8")
    return code(
        "# Copied from app/schemas/resolution.py by scripts/build_notebooks.py. Do not edit here.\n"
        + source
    )


GENERATE = code(
    """
    def generate(model, messages, max_new_tokens=MAX_NEW_TOKENS):
        \"\"\"Greedy decode for one chat (system + user); returns the reply and its latency.\"\"\"
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
        started = time.perf_counter()
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False, use_cache=True)
        new_tokens = out[0][inputs["input_ids"].shape[1]:]
        latency_ms = int((time.perf_counter() - started) * 1000)
        return tokenizer.decode(new_tokens, skip_special_tokens=True), latency_ms, len(new_tokens)
    """
)


# --- 01: fine-tune -------------------------------------------------------------

FINETUNE: list[Cell] = [
    md(
        """
        # ProxyLens 01: QLoRA fine-tune of Qwen2.5-3B (resolution extraction)

        **What:** fine-tunes `Qwen2.5-3B-Instruct` with QLoRA (4-bit, LoRA r=16) to turn one AGM/EGM
        agenda item into `ResolutionExtraction` JSON, distilled from the teacher's labels.

        **Inputs:** the private HF dataset `<you>/proxylens-sft-v1` (from `scripts/push_sft_to_hub.py`);
        Colab secret `HF_TOKEN` with write access.

        **Outputs:** LoRA adapter at `<you>/proxylens-qwen3b-lora-v1` and a `Q4_K_M` GGUF at
        `<you>/proxylens-qwen3b-gguf-v1` (both private), plus `metrics.json` with val JSON validity and
        type accuracy.

        **Runtime:** free T4, about 1.5-2.5 h for 3 epochs (~1,370 examples, ~1,500 tokens each).
        Checkpoints go to Google Drive every 20 steps; re-run all cells after a disconnect and training
        resumes from the last checkpoint.

        **Hyper-parameters (SPEC 7.3):** r=16, alpha=16, dropout 0, all attention + MLP projections;
        lr 2e-4 cosine, 3 epochs, effective batch 16 (2 x 8), fp16 on T4, seed 3407; loss on assistant
        tokens only.
        """
    ),
    md("## 1. Install and configure"),
    INSTALL,
    SETUP,
    code(
        """
        EPOCHS = 3
        LR = 2e-4
        BATCH, GRAD_ACCUM = 2, 8
        EVAL_SUBSET = 32          # val items generated after each epoch (full val runs at the end)
        drive.mount("/content/drive")
        OUTPUT_DIR = "/content/drive/MyDrive/proxylens/qwen3b-lora-v1"
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        """
    ),
    md("## 2. Data"),
    code(
        """
        from datasets import load_dataset

        data_dir = snapshot_download(DATASET_REPO, repo_type="dataset", token=HF_TOKEN,
                                     allow_patterns=["sft/*"])
        ds = load_dataset("json", data_files={"train": f"{data_dir}/sft/train.jsonl",
                                              "val": f"{data_dir}/sft/val.jsonl"})
        print(ds)
        print(ds["train"][0]["messages"][1]["content"][:400])
        """
    ),
    schema_cell(),
    md("## 3. Model + LoRA"),
    code(
        """
        model, tokenizer = FastLanguageModel.from_pretrained(
            BASE_MODEL, max_seq_length=MAX_SEQ_LEN, load_in_4bit=True, dtype=None
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=16,
            lora_alpha=16,
            lora_dropout=0,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
            bias="none",
            use_gradient_checkpointing="unsloth",
            random_state=SEED,
        )
        """
    ),
    code(
        """
        def to_text(batch):
            return {"text": [tokenizer.apply_chat_template(m, tokenize=False) for m in batch["messages"]]}

        train_ds = ds["train"].map(to_text, batched=True, remove_columns=["messages"])
        val_ds = ds["val"].map(to_text, batched=True, remove_columns=["messages"])
        lengths = [len(tokenizer(t).input_ids) for t in train_ds["text"]]
        print("tokens per example: max", max(lengths), "mean", sum(lengths) // len(lengths))
        assert max(lengths) <= MAX_SEQ_LEN, "an example would be truncated"
        """
    ),
    md("## 4. Per-epoch extraction metrics (JSON validity, type accuracy)"),
    GENERATE,
    code(
        """
        from transformers import TrainerCallback

        def score(model, rows):
            \"\"\"JSON validity before any repair, and resolution_type accuracy vs the teacher.\"\"\"
            FastLanguageModel.for_inference(model)
            valid = type_ok = 0
            for row in rows:
                text, _, _ = generate(model, row["messages"][:2])
                target = json.loads(row["messages"][2]["content"])
                try:
                    pred = ResolutionExtraction.model_validate_json(text)
                except Exception:
                    continue
                valid += 1
                type_ok += pred.resolution_type.value == target["resolution_type"]
            FastLanguageModel.for_training(model)
            return {"json_valid": valid / len(rows), "type_acc": type_ok / len(rows), "n": len(rows)}

        class ExtractionEvalCallback(TrainerCallback):
            def __init__(self, rows):
                self.rows, self.history = rows, []

            def on_epoch_end(self, args, state, control, model=None, **kwargs):
                metrics = {"epoch": round(state.epoch, 2), **score(model, self.rows)}
                self.history.append(metrics)
                print("val subset:", metrics)

        eval_rows = ds["val"].shuffle(seed=SEED).select(range(min(EVAL_SUBSET, len(ds["val"]))))
        extraction_cb = ExtractionEvalCallback(eval_rows)
        """
    ),
    md("## 5. Trainer (loss on assistant tokens only)"),
    code(
        """
        import inspect
        from trl import SFTConfig, SFTTrainer
        from unsloth import is_bfloat16_supported
        from unsloth.chat_templates import train_on_responses_only

        def sft_config(**kwargs):
            \"\"\"SFTConfig across TRL versions (max_seq_length -> max_length, eval_strategy naming).\"\"\"
            params = inspect.signature(SFTConfig).parameters
            if "max_seq_length" not in params and "max_length" in params:
                kwargs["max_length"] = kwargs.pop("max_seq_length")
            if "eval_strategy" not in params:
                kwargs["evaluation_strategy"] = kwargs.pop("eval_strategy")
            return SFTConfig(**kwargs)

        args = sft_config(
            output_dir=OUTPUT_DIR,
            dataset_text_field="text",
            max_seq_length=MAX_SEQ_LEN,
            packing=False,
            per_device_train_batch_size=BATCH,
            gradient_accumulation_steps=GRAD_ACCUM,
            num_train_epochs=EPOCHS,
            learning_rate=LR,
            lr_scheduler_type="cosine",
            warmup_ratio=0.05,
            weight_decay=0.01,
            optim="adamw_8bit",
            fp16=not is_bfloat16_supported(),
            bf16=is_bfloat16_supported(),
            logging_steps=5,
            eval_strategy="epoch",
            per_device_eval_batch_size=BATCH,
            save_strategy="steps",
            save_steps=20,
            save_total_limit=3,
            seed=SEED,
            report_to="none",
        )
        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            args=args,
            callbacks=[extraction_cb],
        )
        trainer = train_on_responses_only(
            trainer,
            instruction_part="<|im_start|>user\\n",
            response_part="<|im_start|>assistant\\n",
        )
        """
    ),
    code(
        """
        # Sanity check: only the assistant JSON should carry loss.
        labels = [t for t in trainer.train_dataset[0]["labels"] if t != -100]
        print(tokenizer.decode(labels)[:300])
        """
    ),
    md("## 6. Train (resumes from the latest Drive checkpoint)"),
    code(
        """
        checkpoints = sorted(glob.glob(f"{OUTPUT_DIR}/checkpoint-*"), key=lambda p: int(p.rsplit("-", 1)[1]))
        resume = checkpoints[-1] if checkpoints else None
        print("resuming from", resume)
        train_stats = trainer.train(resume_from_checkpoint=resume)
        print(train_stats)
        """
    ),
    md("## 7. Full validation + metrics"),
    code(
        """
        final = score(model, ds["val"])
        metrics = {
            "base_model": BASE_MODEL,
            "train_examples": len(ds["train"]),
            "val_examples": len(ds["val"]),
            "epochs": EPOCHS,
            "final_val": final,
            "per_epoch_val_subset": extraction_cb.history,
            "train_loss_log": [h for h in trainer.state.log_history if "loss" in h],
            "eval_loss_log": [h for h in trainer.state.log_history if "eval_loss" in h],
        }
        with open(f"{OUTPUT_DIR}/metrics.json", "w") as fh:
            json.dump(metrics, fh, indent=2)
        print(json.dumps(final, indent=2))
        """
    ),
    md("## 8. Save the LoRA adapter (private HF repo)"),
    code(
        """
        model.save_pretrained(f"{OUTPUT_DIR}/final")
        tokenizer.save_pretrained(f"{OUTPUT_DIR}/final")
        model.push_to_hub(LORA_REPO, token=HF_TOKEN, private=True)
        tokenizer.push_to_hub(LORA_REPO, token=HF_TOKEN, private=True)
        HfApi(token=HF_TOKEN).upload_file(path_or_fileobj=f"{OUTPUT_DIR}/metrics.json",
                                          path_in_repo="metrics.json", repo_id=LORA_REPO)
        """
    ),
    md("## 9. Export a merged Q4_K_M GGUF for CPU serving (llama.cpp)"),
    code(
        """
        model.save_pretrained_gguf("gguf_out", tokenizer, quantization_method="q4_k_m")
        candidates = [p for p in glob.glob("**/*.gguf", recursive=True) if "q4_k_m" in p.lower()]
        assert candidates, "GGUF export produced no Q4_K_M file"
        gguf_path = max(candidates, key=os.path.getmtime)
        print(gguf_path, round(os.path.getsize(gguf_path) / 1e9, 2), "GB")

        api = HfApi(token=HF_TOKEN)
        api.create_repo(GGUF_REPO, private=True, exist_ok=True)
        api.upload_file(path_or_fileobj=gguf_path, path_in_repo=GGUF_FILE, repo_id=GGUF_REPO)
        print(f"Uploaded https://huggingface.co/{GGUF_REPO}/blob/main/{GGUF_FILE}")
        """
    ),
    md(
        """
        ## Next

        In the repo's `.env` set `STUDENT_GGUF_REPO=<you>/proxylens-qwen3b-gguf-v1` (and `HF_TOKEN`), then run
        the Phase 4 smoke test:

        ```bash
        uv sync --extra student
        uv run python -m scripts.smoke_student --n 10
        ```
        """
    ),
]


# --- 02: eval predictions -------------------------------------------------------

EVAL: list[Cell] = [
    md(
        """
        # ProxyLens 02: base vs fine-tuned predictions on GPU

        **What:** runs the base `Qwen2.5-3B-Instruct` (zero-shot, same prompt) and the fine-tuned LoRA on
        an eval split and saves raw outputs. Metrics are **not** computed here: the repo's eval harness
        (`eval/`, Phase 7) scores every provider the same way, and the gold labels never leave the repo.

        **Inputs:** `<you>/proxylens-sft-v1` (`eval_inputs/test.jsonl` = gold-split prompts without labels,
        `eval_inputs/val.jsonl`); the LoRA from notebook 01; Colab secret `HF_TOKEN`.

        **Outputs:** `eval/results/<run_id>.json` per model (format in `eval/README.md`), uploaded to the
        dataset repo under `results/` and offered as a download.

        **Runtime:** free T4, roughly 10-25 s per item per model; ~184 test items x 2 models ≈ 1.5-2.5 h.
        Each model's results are saved as soon as it finishes.
        """
    ),
    INSTALL,
    SETUP,
    code(
        """
        SPLIT = "test"   # "test" = gold-split items (score after hand-labelling); "val" = teacher-labelled
        LIMIT = None     # e.g. 20 for a quick run
        inputs_dir = snapshot_download(DATASET_REPO, repo_type="dataset", token=HF_TOKEN,
                                       allow_patterns=["eval_inputs/*"])
        rows = [json.loads(line) for line in open(f"{inputs_dir}/eval_inputs/{SPLIT}.jsonl")]
        rows = rows[:LIMIT] if LIMIT else rows
        print(len(rows), "items from", SPLIT)
        """
    ),
    GENERATE,
    code(
        """
        import datetime, gc

        def run(provider, model_id):
            global tokenizer
            model, tokenizer = FastLanguageModel.from_pretrained(
                model_id, max_seq_length=MAX_SEQ_LEN, load_in_4bit=True, dtype=None, token=HF_TOKEN
            )
            FastLanguageModel.for_inference(model)
            items = []
            for i, row in enumerate(rows):
                text, latency_ms, n_tokens = generate(model, row["messages"])
                items.append({"item_id": row["item_id"], "output_text": text,
                              "latency_ms": latency_ms, "output_tokens": n_tokens})
                if i % 20 == 0:
                    print(provider, i, latency_ms, "ms")
            stamp = datetime.datetime.now(datetime.timezone.utc)
            result = {
                "run_id": f"{stamp:%Y-%m-%d}_{provider}_{SPLIT}",
                "provider": provider,
                "model": model_id,
                "split": SPLIT,
                "created_at": stamp.isoformat(),
                "hardware": torch.cuda.get_device_name(0),
                "decoding": {"greedy": True, "max_new_tokens": MAX_NEW_TOKENS, "constrained": False},
                "items": items,
            }
            os.makedirs("results", exist_ok=True)
            path = f"results/{result['run_id']}.json"
            with open(path, "w") as fh:
                json.dump(result, fh)
            HfApi(token=HF_TOKEN).upload_file(path_or_fileobj=path, path_in_repo=path,
                                              repo_id=DATASET_REPO, repo_type="dataset")
            del model
            gc.collect(); torch.cuda.empty_cache()
            return path
        """
    ),
    code(
        """
        paths = [
            run("base_hf", BASE_MODEL),
            run("finetuned_lora", LORA_REPO),
        ]
        print(paths)
        """
    ),
    code(
        """
        from google.colab import files
        for path in paths:
            files.download(path)   # copy into the repo's eval/results/
        """
    ),
]


def write_all() -> list[Path]:
    NOTEBOOKS.mkdir(exist_ok=True)
    targets = {
        NOTEBOOKS / "01_finetune_qlora.ipynb": FINETUNE,
        NOTEBOOKS / "02_eval_student.ipynb": EVAL,
    }
    for path, cells in targets.items():
        path.write_text(json.dumps(notebook(cells), indent=1) + "\n", encoding="utf-8")
    return list(targets)


def main() -> int:
    for path in write_all():
        print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
