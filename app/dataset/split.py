"""Company-grouped splits (SPEC 7.2 step 6): no company appears in two splits."""

import hashlib
import re
from enum import StrEnum

# Buckets out of 100: train 80, val 10, and 10 reserved for the human gold set.
TRAIN_UPPER = 80
VAL_UPPER = 90

_SUFFIXES = re.compile(r"\b(limited|ltd|private|pvt|india|the|and|&)\b\.?", re.IGNORECASE)


class Split(StrEnum):
    TRAIN = "train"
    VAL = "val"
    GOLD = "gold"  # companies held back for hand-labelled test items


def company_key(company: str) -> str:
    """Normalise names so 'ITC Ltd.' and 'ITC Limited' land in the same split."""
    cleaned = _SUFFIXES.sub(" ", company.lower())
    return re.sub(r"[^a-z0-9]+", "", cleaned)


def assign_split(company: str, salt: str = "proxylens-v1") -> Split:
    """Deterministic split from a hash of the normalised company name."""
    key = company_key(company)
    if not key:
        raise ValueError("company name is required for a grouped split")
    bucket = int(hashlib.sha256(f"{salt}:{key}".encode()).hexdigest(), 16) % 100
    if bucket < TRAIN_UPPER:
        return Split.TRAIN
    return Split.VAL if bucket < VAL_UPPER else Split.GOLD
