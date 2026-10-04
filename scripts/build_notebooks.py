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


def notebook(cells: list[Cell], *, gpu: bool = True) -> dict[str, Any]:
    def as_cell(kind: str, source: str) -> dict[str, Any]:
        lines = source.splitlines(keepends=True)
        cell: dict[str, Any] = {"cell_type": kind, "metadata": {}, "source": lines}
        if kind == "code":
            cell |= {"execution_count": None, "outputs": []}
        return cell

    metadata: dict[str, Any] = {
        "colab": {"provenance": []},
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
    }
    if gpu:
        metadata = {"accelerator": "GPU", **metadata, "colab": {"gpuType": "T4", "provenance": []}}
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": metadata,
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
    import os
    # Must be set before torch starts: reduces fragmentation-driven OOMs on the 15 GB T4.
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

    from unsloth import FastLanguageModel  # import before transformers/trl: Unsloth patches them

    import glob, json, time
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

    import transformers
    transformers.utils.logging.set_verbosity_error()  # hides a harmless per-generate max_length warning
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


SAVE_AND_EXPORT: list[Cell] = [
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


# Checkpoint selection and metrics shared by the export notebooks (03 GPU, 04 CPU).
PICK_CHECKPOINT = code(
    """
    drive.mount("/content/drive")
    OUTPUT_DIR = "/content/drive/MyDrive/proxylens/qwen3b-lora-v1"
    CHECKPOINT = None   # e.g. f"{OUTPUT_DIR}/checkpoint-130" to choose one; None = latest complete

    def complete(path):
        # Finished syncing to Drive: adapter weights + trainer state present.
        weights = os.path.join(path, "adapter_model.safetensors")
        return (os.path.isfile(weights) and os.path.getsize(weights) > 50_000_000
                and os.path.isfile(os.path.join(path, "trainer_state.json")))

    found = sorted(glob.glob(f"{OUTPUT_DIR}/checkpoint-*"), key=lambda p: int(p.rsplit("-", 1)[1]))
    for path in found:
        print(f"{os.path.basename(path):16} {'complete' if complete(path) else 'INCOMPLETE (skipped)'}")
    if CHECKPOINT is None:
        usable = [p for p in found if complete(p)]
        assert usable, f"no complete checkpoint in {OUTPUT_DIR}"
        CHECKPOINT = usable[-1]
    print("using", CHECKPOINT)
    """
)

CHECKPOINT_METRICS = code(
    """
    # metrics.json from the trainer state saved with the checkpoint.
    state = json.load(open(f"{CHECKPOINT}/trainer_state.json"))
    metrics = {
        "base_model": BASE_MODEL,
        "checkpoint": os.path.basename(CHECKPOINT),
        "epochs": state.get("epoch"),
        "global_step": state.get("global_step"),
        "train_loss_log": [h for h in state["log_history"] if "loss" in h],
        "eval_loss_log": [h for h in state["log_history"] if "eval_loss" in h],
        "sanity_check": SANITY,
    }
    with open(f"{OUTPUT_DIR}/metrics.json", "w") as fh:
        json.dump(metrics, fh, indent=2)
    print(json.dumps(metrics["eval_loss_log"], indent=2))
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

        **Runtime:** free T4, about 2 h per epoch (~1,370 examples, ~1,500 tokens each; ~80 s per
        optimizer step). Default is 1 epoch: a 2-epoch run gave no gain on the val subset. Checkpoints go to Google Drive every 10 steps; after a
        disconnect, re-run all cells and training resumes from the last checkpoint.

        **Hyper-parameters (SPEC 7.3):** r=16, alpha=16, dropout 0, all attention + MLP projections;
        lr 2e-4 cosine, 1 epoch (see the config cell), effective batch 16 (1 x 16 to fit T4 memory), fp16 on T4,
        seed 3407; loss on assistant tokens only.
        """
    ),
    md("## 1. Install and configure"),
    INSTALL,
    SETUP,
    code(
        """
        # First run (v1): 2 epochs gave val loss 0.191 -> 0.182 and identical subset metrics
        # (96.9% valid JSON, 93.8% type accuracy) after epochs 1 and 2, so 1 epoch is the default.
        EPOCHS = 1
        FULL_VAL_EVAL = False     # generating all 137 val answers adds ~1 h; notebook 02 / Phase 7 evaluate properly
        LR = 2e-4
        # Effective batch 16 as in SPEC 7.3. One sequence per device step: two ~4k-token sequences
        # plus the 152k-vocab logits do not fit in a T4's 15 GB.
        BATCH, GRAD_ACCUM = 1, 16
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
            save_steps=10,
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
    md("## 7. Metrics (full validation only if FULL_VAL_EVAL)"),
    code(
        """
        final = score(model, ds["val"]) if FULL_VAL_EVAL else None
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
    *SAVE_AND_EXPORT,
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


# --- 03: export an already-trained checkpoint ---------------------------------------

EXPORT: list[Cell] = [
    md(
        """
        # ProxyLens 03: export a trained checkpoint (no training)

        **When:** notebook 01 finished training but the session ended before the upload/GGUF cells (a
        long Colab session can run out of time or GPU memory). This loads the latest checkpoint from
        Google Drive in a fresh session and does only the remaining steps.

        **Inputs:** the Drive folder notebook 01 wrote (`MyDrive/proxylens/qwen3b-lora-v1/checkpoint-*`);
        Colab secret `HF_TOKEN`.

        **Outputs:** the same as notebook 01: LoRA adapter + `metrics.json` at
        `<you>/proxylens-qwen3b-lora-v1` and `proxylens-q4_k_m.gguf` at `<you>/proxylens-qwen3b-gguf-v1`.

        **Runtime:** free T4, about 20-40 min (mostly the GGUF conversion).
        """
    ),
    INSTALL,
    SETUP,
    PICK_CHECKPOINT,
    code(
        """
        # The checkpoint holds the LoRA adapter; Unsloth loads the 4-bit base model under it.
        model, tokenizer = FastLanguageModel.from_pretrained(
            CHECKPOINT, max_seq_length=MAX_SEQ_LEN, load_in_4bit=True, dtype=None
        )
        FastLanguageModel.for_inference(model)
        """
    ),
    schema_cell(),
    GENERATE,
    code(
        """
        # Sanity check before uploading: the adapter must produce valid extractions.
        from datasets import load_dataset

        data_dir = snapshot_download(DATASET_REPO, repo_type="dataset", token=HF_TOKEN,
                                     allow_patterns=["sft/val.jsonl"])
        val = load_dataset("json", data_files=f"{data_dir}/sft/val.jsonl")["train"]
        ok = 0
        for row in val.select(range(5)):
            text, latency_ms, _ = generate(model, row["messages"][:2])
            try:
                pred = ResolutionExtraction.model_validate_json(text)
                ok += 1
                print("valid", pred.resolution_type.value, f"{latency_ms} ms")
            except Exception as exc:
                print("INVALID:", str(exc)[:200])
        assert ok >= 4, "adapter does not look trained; check CHECKPOINT"
        SANITY = f"{ok}/5 valid"
        """
    ),
    CHECKPOINT_METRICS,
    *SAVE_AND_EXPORT,
]


# --- 04: export on a CPU-only runtime -------------------------------------------------

EXPORT_CPU: list[Cell] = [
    md(
        """
        # ProxyLens 04: export a trained checkpoint on CPU (no GPU needed)

        **When:** like notebook 03, but for when Colab offers no GPU (free T4 quota used up). Training is
        already done; merging the LoRA, converting to GGUF and quantizing all run on CPU. Use
        *Runtime > Change runtime type > CPU*.

        **How:** plain `transformers` + `peft` merge the adapter into the full-precision
        `Qwen2.5-3B-Instruct` (bf16, ~6.2 GB of the ~12 GB RAM), then llama.cpp's own
        `convert_hf_to_gguf.py` and `llama-quantize` produce `Q4_K_M`. This is what Unsloth's
        `save_pretrained_gguf` does in notebooks 01/03.

        **Inputs:** the Drive folder notebook 01 wrote (`MyDrive/proxylens/qwen3b-lora-v1/checkpoint-*`);
        Colab secret `HF_TOKEN` with write access.

        **Outputs:** LoRA adapter + `metrics.json` at `<you>/proxylens-qwen3b-lora-v1` and
        `proxylens-q4_k_m.gguf` at `<you>/proxylens-qwen3b-gguf-v1`.

        **Runtime:** about 30-45 min on the free CPU runtime (building llama-quantize and quantizing
        take the longest).
        """
    ),
    code(
        """
        %%capture
        !pip install -q "peft>=0.13" "huggingface_hub>=0.25" "pydantic>=2.8" sentencepiece
        # Colab preinstalls torchao 0.10, which newer peft refuses to import; the merge does not use it.
        !pip uninstall -q -y torchao
        # llama.cpp: the HF -> GGUF converter, and the quantizer built from source (CPU only).
        !git clone -q --depth 1 https://github.com/ggml-org/llama.cpp
        !cmake -S llama.cpp -B llama.cpp/build -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF
        !cmake --build llama.cpp/build --target llama-quantize -j 4
        # Prebuilt CPU wheel, for the sanity check on the finished GGUF.
        !pip install -q llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
        """
    ),
    code(
        """
        import gc, glob, json, os, shutil, subprocess
        import torch
        from google.colab import drive, userdata
        from huggingface_hub import HfApi, snapshot_download

        QUANTIZE = "llama.cpp/build/bin/llama-quantize"
        assert os.path.isfile(QUANTIZE), "llama-quantize did not build; re-run the install cell without %%capture"
        print("torch", torch.__version__, "| CPU threads:", os.cpu_count())

        HF_TOKEN = userdata.get("HF_TOKEN")  # Colab secret; needs write access
        HF_USER = HfApi(token=HF_TOKEN).whoami()["name"]
        DATASET_REPO = f"{HF_USER}/proxylens-sft-v1"
        LORA_REPO = f"{HF_USER}/proxylens-qwen3b-lora-v1"
        GGUF_REPO = f"{HF_USER}/proxylens-qwen3b-gguf-v1"
        GGUF_FILE = "proxylens-q4_k_m.gguf"                     # = STUDENT_GGUF_FILE in .env
        BASE_MODEL = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit"     # what the adapter was trained on
        MERGE_BASE = "unsloth/Qwen2.5-3B-Instruct"              # same weights, full precision
        print("HF user:", HF_USER)
        """
    ),
    PICK_CHECKPOINT,
    md("## Merge the adapter into the full-precision base"),
    code(
        """
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        base = AutoModelForCausalLM.from_pretrained(MERGE_BASE, torch_dtype=torch.bfloat16,
                                                    low_cpu_mem_usage=True, token=HF_TOKEN)
        merged = PeftModel.from_pretrained(base, CHECKPOINT).merge_and_unload()
        has_tokenizer = os.path.isfile(f"{CHECKPOINT}/tokenizer_config.json")
        tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT if has_tokenizer else MERGE_BASE)
        merged.save_pretrained("merged", safe_serialization=True)
        tokenizer.save_pretrained("merged")
        del base, merged
        gc.collect()
        print(sorted(os.listdir("merged")))
        """
    ),
    md("## Convert to GGUF and quantize to Q4_K_M"),
    code(
        """
        def run(cmd):
            print("$", " ".join(cmd))
            subprocess.run(cmd, check=True)

        run(["python", "llama.cpp/convert_hf_to_gguf.py", "merged", "--outfile", "proxylens-f16.gguf",
             "--outtype", "f16"])
        shutil.rmtree("merged")   # free disk before quantizing
        run([QUANTIZE, "proxylens-f16.gguf", GGUF_FILE, "Q4_K_M", str(os.cpu_count())])
        os.remove("proxylens-f16.gguf")
        print(GGUF_FILE, round(os.path.getsize(GGUF_FILE) / 1e9, 2), "GB")
        """
    ),
    schema_cell(),
    code(
        """
        # Sanity check before uploading: the quantized model must produce valid extractions.
        # Unconstrained decoding, so this measures the model, not the JSON grammar. ~1-2 min per item.
        from llama_cpp import Llama

        data_dir = snapshot_download(DATASET_REPO, repo_type="dataset", token=HF_TOKEN,
                                     allow_patterns=["sft/val.jsonl"])
        val = [json.loads(line) for line in open(f"{data_dir}/sft/val.jsonl")][:3]
        llm = Llama(model_path=GGUF_FILE, n_ctx=4096, n_threads=os.cpu_count(), verbose=False)
        ok = 0
        for row in val:
            out = llm.create_chat_completion(messages=row["messages"][:2], temperature=0.0, max_tokens=1024)
            text = out["choices"][0]["message"]["content"]
            try:
                pred = ResolutionExtraction.model_validate_json(text)
                ok += 1
                print("valid", pred.resolution_type.value)
            except Exception as exc:
                print("INVALID:", str(exc)[:200])
        del llm
        assert ok >= 2, "quantized model does not look trained; check CHECKPOINT"
        SANITY = f"{ok}/3 valid (Q4_K_M, CPU)"
        """
    ),
    CHECKPOINT_METRICS,
    md("## Upload the LoRA adapter and the GGUF (private HF repos)"),
    code(
        """
        api = HfApi(token=HF_TOKEN)
        api.create_repo(LORA_REPO, private=True, exist_ok=True)
        # Adapter + tokenizer only; optimizer/scheduler/RNG state stays on Drive.
        api.upload_folder(folder_path=CHECKPOINT, repo_id=LORA_REPO,
                          allow_patterns=["adapter_*", "*.json", "*.jinja", "merges.txt"],
                          ignore_patterns=["trainer_state.json", "training_args*", "rng_state*"])
        api.upload_file(path_or_fileobj=f"{OUTPUT_DIR}/metrics.json", path_in_repo="metrics.json",
                        repo_id=LORA_REPO)

        api.create_repo(GGUF_REPO, private=True, exist_ok=True)
        api.upload_file(path_or_fileobj=GGUF_FILE, path_in_repo=GGUF_FILE, repo_id=GGUF_REPO)
        print(f"Uploaded https://huggingface.co/{GGUF_REPO}/blob/main/{GGUF_FILE}")
        """
    ),
    SAVE_AND_EXPORT[-1],  # "Next": the local smoke test
]


def write_all() -> list[Path]:
    NOTEBOOKS.mkdir(exist_ok=True)
    targets = {
        NOTEBOOKS / "01_finetune_qlora.ipynb": FINETUNE,
        NOTEBOOKS / "02_eval_student.ipynb": EVAL,
        NOTEBOOKS / "03_export_checkpoint.ipynb": EXPORT,
    }
    for path, cells in targets.items():
        path.write_text(json.dumps(notebook(cells), indent=1) + "\n", encoding="utf-8")
    cpu_path = NOTEBOOKS / "04_export_cpu.ipynb"
    cpu_path.write_text(
        json.dumps(notebook(EXPORT_CPU, gpu=False), indent=1) + "\n", encoding="utf-8"
    )
    return [*targets, cpu_path]


def main() -> int:
    for path in write_all():
        print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
