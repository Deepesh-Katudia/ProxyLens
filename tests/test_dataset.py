import json
from collections import Counter
from pathlib import Path

import pytest

from app.dataset.manifest import NoticeEntry, read_manifest, write_manifest
from app.dataset.sft import sft_record
from app.dataset.split import Split, assign_split, company_key
from app.llm.prompts import EXTRACTION_SYSTEM_PROMPT
from app.schemas.resolution import ResolutionExtraction, ResolutionType
from scripts.make_sft import build


def _extraction(rtype: ResolutionType) -> ResolutionExtraction:
    return ResolutionExtraction(
        item_no=1, title="t", resolution_type=rtype, is_special_resolution=False
    )


@pytest.mark.parametrize(
    ("a", "b"),
    [("ITC Limited", "ITC Ltd."), ("Tata Consumer Products Ltd", "TATA CONSUMER PRODUCTS LIMITED")],
)
def test_company_names_normalise_to_one_split(a: str, b: str) -> None:
    assert company_key(a) == company_key(b)
    assert assign_split(a) is assign_split(b)


def test_split_is_roughly_80_10_10() -> None:
    counts = Counter(assign_split(f"Company {i} Limited") for i in range(5000))

    assert 0.76 < counts[Split.TRAIN] / 5000 < 0.84
    assert 0.07 < counts[Split.VAL] / 5000 < 0.13
    assert 0.07 < counts[Split.GOLD] / 5000 < 0.13


def test_split_requires_a_company_name() -> None:
    with pytest.raises(ValueError):
        assign_split("Ltd.")


def test_manifest_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    entries = [
        NoticeEntry(file="b.pdf", company="B Ltd"),
        NoticeEntry(file="a.pdf", sha256="ab" * 32),
    ]

    write_manifest(path, entries)

    assert [e.file for e in read_manifest(path)] == ["a.pdf", "b.pdf"]
    assert read_manifest(path)[0].doc_id == "ab" * 6


def test_sft_record_uses_shared_prompt_and_compact_json() -> None:
    record = sft_record(2, "To declare dividend.", None, _extraction(ResolutionType.DIVIDEND))

    system, user, assistant = record["messages"]
    assert system["content"] == EXTRACTION_SYSTEM_PROMPT
    assert user["content"].startswith("AGENDA ITEM No. 2:\nTo declare dividend.")
    assert json.loads(assistant["content"])["resolution_type"] == "DIVIDEND"


def _company_in(split: Split) -> str:
    return next(f"Co {i} Ltd" for i in range(1000) if assign_split(f"Co {i} Ltd") is split)


def test_build_keeps_gold_unlabelled_and_filters_disagreements() -> None:
    train_co, gold_co = _company_in(Split.TRAIN), _company_in(Split.GOLD)
    items = [
        {"item_id": "a-1", "item_no": 1, "company": train_co, "text": "x"},
        {"item_id": "a-2", "item_no": 2, "company": train_co, "text": "y"},
        {"item_id": "g-1", "item_no": 1, "company": gold_co, "text": "z"},
        {"item_id": "n-1", "item_no": 1, "company": "", "text": "w"},
    ]
    labels = {
        "a-1": _extraction(ResolutionType.DIVIDEND),
        "a-2": _extraction(ResolutionType.ESOP),
        "g-1": _extraction(ResolutionType.OTHER),
    }
    second = {"a-1": _extraction(ResolutionType.DIVIDEND), "a-2": _extraction(ResolutionType.OTHER)}

    splits, stats = build(items, labels, second)

    assert len(splits[Split.TRAIN]) == 1  # a-2 dropped: teachers disagree
    assert splits[Split.GOLD] == [items[2]]  # raw item, no teacher label attached
    assert stats["filtering"] == {"skipped_no_company": 1, "dropped_teacher_disagreement": 1}
