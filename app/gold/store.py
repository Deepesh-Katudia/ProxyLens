"""File-backed store for the human gold set (SPEC 7.2 step 5).

Candidates come from `scripts.make_sft` (items of gold-split companies, never
teacher-labelled). Labels are appended to a JSONL file; the latest row per item
wins, so edits are just new rows and history is kept.
"""

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.dataset.jsonl import append_jsonl, read_jsonl
from app.schemas.resolution import ResolutionExtraction

DEFAULT_CANDIDATES = Path("data/gold/candidates.jsonl")
DEFAULT_LABELS = Path("data/gold/labels.jsonl")


class LabelStatus(StrEnum):
    LABELLED = "labelled"
    SKIPPED = "skipped"  # not a real resolution (segmentation error) or unreadable


class GoldLabel(BaseModel):
    status: LabelStatus
    extraction: ResolutionExtraction | None = None
    skip_reason: str | None = Field(default=None, max_length=500)
    labeller: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def _consistent(self) -> "GoldLabel":
        if self.status is LabelStatus.LABELLED and self.extraction is None:
            raise ValueError("a labelled item needs an extraction")
        if self.status is LabelStatus.SKIPPED and not self.skip_reason:
            raise ValueError("a skipped item needs a skip_reason")
        return self


class GoldItemSummary(BaseModel):
    item_id: str
    company: str
    item_no: int
    preview: str
    status: LabelStatus | None


class GoldItem(BaseModel):
    item_id: str
    company: str
    file: str
    item_no: int
    section: str | None
    resolution_kind_hint: str | None
    text: str
    explanatory_statement: str | None
    label: GoldLabel | None


@dataclass
class GoldStore:
    candidates_path: Path = DEFAULT_CANDIDATES
    labels_path: Path = DEFAULT_LABELS

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def _candidates(self) -> list[dict[str, Any]]:
        return list(read_jsonl(self.candidates_path))

    def _labels(self) -> dict[str, GoldLabel]:
        latest: dict[str, GoldLabel] = {}
        for row in read_jsonl(self.labels_path):
            latest[row["item_id"]] = GoldLabel.model_validate(row["label"])
        return latest

    def list_items(self) -> list[GoldItemSummary]:
        labels = self._labels()
        return [
            GoldItemSummary(
                item_id=c["item_id"],
                company=c.get("company", ""),
                item_no=c["item_no"],
                preview=" ".join(c["text"].split())[:160],
                status=labels[c["item_id"]].status if c["item_id"] in labels else None,
            )
            for c in self._candidates()
        ]

    def get_item(self, item_id: str) -> GoldItem | None:
        candidate = next((c for c in self._candidates() if c["item_id"] == item_id), None)
        if candidate is None:
            return None
        return GoldItem(
            item_id=candidate["item_id"],
            company=candidate.get("company", ""),
            file=candidate.get("file", ""),
            item_no=candidate["item_no"],
            section=candidate.get("section"),
            resolution_kind_hint=candidate.get("resolution_kind_hint"),
            text=candidate["text"],
            explanatory_statement=candidate.get("explanatory_statement"),
            label=self._labels().get(item_id),
        )

    def save_label(self, item_id: str, label: GoldLabel) -> None:
        if not any(c["item_id"] == item_id for c in self._candidates()):
            raise KeyError(item_id)
        row = {
            "item_id": item_id,
            "label": label.model_dump(mode="json"),
            "saved_at": datetime.now(UTC).isoformat(),
        }
        with self._lock:
            append_jsonl(self.labels_path, row)

    def labelled(self) -> dict[str, GoldLabel]:
        return self._labels()
