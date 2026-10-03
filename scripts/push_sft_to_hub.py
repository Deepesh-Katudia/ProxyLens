"""Upload the fine-tuning data to a private HF Hub dataset for the Colab notebooks.

    uv run python -m scripts.push_sft_to_hub                # <you>/proxylens-sft-v1
    uv run python -m scripts.push_sft_to_hub --repo me/x    # explicit repo id
    uv run python -m scripts.push_sft_to_hub --dry-run      # build the folder only

Uploads:
  sft/train.jsonl, sft/val.jsonl      chat-format training data (teacher labels)
  eval_inputs/val.jsonl               val prompts (system + user messages only)
  eval_inputs/test.jsonl              gold-split prompts, with NO labels
Gold labels never leave this machine; metrics are computed locally (Phase 7).
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.dataset.jsonl import read_jsonl, write_jsonl
from app.llm.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_input
from scripts.make_sft import GOLD_CANDIDATES, SFT_DIR

logger = logging.getLogger("push_sft_to_hub")

STAGING = Path("data/hub_staging")
DEFAULT_REPO_NAME = "proxylens-sft-v1"


def eval_input(item_id: str, item_no: int, text: str, statement: str | None) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "messages": [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": build_extraction_input(item_no, text, statement)},
        ],
    }


def val_inputs() -> list[dict[str, Any]]:
    """Val prompts in the same order as sft/val.jsonl, minus the answers."""
    rows = []
    for i, row in enumerate(read_jsonl(SFT_DIR / "val.jsonl")):
        rows.append({"item_id": f"val-{i}", "messages": row["messages"][:2]})
    return rows


def test_inputs() -> list[dict[str, Any]]:
    return [
        eval_input(c["item_id"], c["item_no"], c["text"], c.get("explanatory_statement"))
        for c in read_jsonl(GOLD_CANDIDATES)
    ]


def stage() -> Path:
    for name in ("train.jsonl", "val.jsonl"):
        if not (SFT_DIR / name).exists():
            raise SystemExit(f"{SFT_DIR / name} is missing; run scripts.make_sft first")
    write_jsonl(STAGING / "sft" / "train.jsonl", read_jsonl(SFT_DIR / "train.jsonl"))
    write_jsonl(STAGING / "sft" / "val.jsonl", read_jsonl(SFT_DIR / "val.jsonl"))
    write_jsonl(STAGING / "eval_inputs" / "val.jsonl", val_inputs())
    write_jsonl(STAGING / "eval_inputs" / "test.jsonl", test_inputs())
    stats = json.loads((SFT_DIR / "stats.json").read_text(encoding="utf-8"))
    (STAGING / "README.md").write_text(
        "---\nlicense: other\n---\n# ProxyLens SFT data\n\n"
        "Private training data for the ProxyLens resolution extractor. "
        f"Teacher: `{stats['teacher_model']}`. Counts: {json.dumps(stats['counts'])}.\n"
        "See `data/DATASET_CARD.md` in the ProxyLens repo.\n",
        encoding="utf-8",
    )
    return STAGING


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="dataset repo id (default: <hf user>/proxylens-sft-v1)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    folder = stage()
    logger.info("Staged %s", folder)
    if args.dry_run:
        return 0

    from huggingface_hub import HfApi

    token = get_settings().hf_token.get_secret_value()
    if not token:
        raise SystemExit("HF_TOKEN is not set in .env (needs a write token)")
    api = HfApi(token=token)
    repo = args.repo or f"{api.whoami()['name']}/{DEFAULT_REPO_NAME}"
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    api.upload_folder(folder_path=str(folder), repo_id=repo, repo_type="dataset")
    logger.info("Uploaded to https://huggingface.co/datasets/%s (private)", repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
