"""The reference labels the models are scored against, with honest provenance.

Labels live in data/gold/labels.jsonl (local only, gitignored). Whether they are
human gold or model labels is decided from the data, not asserted: a label saved
unchanged from its model draft counts as model-labelled.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.gold.store import DEFAULT_DRAFTS, DEFAULT_LABELS, GoldStore, LabelStatus
from app.schemas.resolution import ResolutionExtraction


@dataclass(frozen=True)
class ReferenceSet:
    labels: dict[str, ResolutionExtraction]  # item_id -> reference extraction
    skipped: int
    from_blank: int  # labelled on an empty form: human labels
    edited_drafts: int  # started from a model draft and changed: human-reviewed
    unedited_drafts: int  # saved exactly as drafted: model labels
    draft_models: tuple[str, ...]

    @property
    def kind(self) -> str:
        if self.unedited_drafts == 0:
            return "human"
        if self.from_blank + self.edited_drafts == 0:
            return "model"
        return "mixed"

    def describe(self) -> str:
        models = ", ".join(self.draft_models) or "none"
        if self.kind == "human":
            return f"Hand-labelled gold set ({len(self.labels)} items)."
        if self.kind == "model":
            return (
                f"Model-labelled reference ({len(self.labels)} items): drafts by {models} saved "
                "without human edits. An independent model, not human gold; the teacher is a "
                "different model family."
            )
        return (
            f"Mixed reference ({len(self.labels)} items): {self.from_blank + self.edited_drafts} "
            f"human-labelled or edited, {self.unedited_drafts} model drafts ({models}) saved "
            "unchanged."
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "description": self.describe(),
            "items": len(self.labels),
            "skipped": self.skipped,
            "from_blank": self.from_blank,
            "edited_drafts": self.edited_drafts,
            "unedited_drafts": self.unedited_drafts,
            "draft_models": list(self.draft_models),
        }


def load_reference(
    labels_path: Path = DEFAULT_LABELS, drafts_path: Path = DEFAULT_DRAFTS
) -> ReferenceSet:
    store = GoldStore(labels_path=labels_path, drafts_path=drafts_path)
    drafts = store.drafts()
    labels: dict[str, ResolutionExtraction] = {}
    skipped = from_blank = edited = unedited = 0
    models: set[str] = set()
    for item_id, label in store.labelled().items():
        if label.status is LabelStatus.SKIPPED or label.extraction is None:
            skipped += 1
            continue
        labels[item_id] = label.extraction
        draft = drafts.get(item_id)
        if label.draft_model is None and draft is None:
            from_blank += 1
            continue
        model, drafted = draft if draft else (label.draft_model or "", None)
        models.add(model)
        same = drafted is not None and _same(drafted, label.extraction)
        if same:
            unedited += 1
        elif label.draft_model is None:
            from_blank += 1
        else:
            edited += 1
    return ReferenceSet(labels, skipped, from_blank, edited, unedited, tuple(sorted(models)))


def _same(a: ResolutionExtraction, b: ResolutionExtraction) -> bool:
    return json.dumps(a.model_dump(mode="json"), sort_keys=True) == json.dumps(
        b.model_dump(mode="json"), sort_keys=True
    )
