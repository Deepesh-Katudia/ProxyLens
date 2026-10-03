"""The notice manifest (`data/raw/notices/manifest.csv`): one row per notice PDF."""

import csv
import hashlib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

MANIFEST_FIELDS = (
    "file",
    "company",
    "bse_code",
    "meeting_type",
    "meeting_date",
    "fiscal_year",
    "source_url",
    "sha256",
)


@dataclass(frozen=True)
class NoticeEntry:
    file: str
    company: str = ""
    bse_code: str = ""
    meeting_type: str = ""
    meeting_date: str = ""
    fiscal_year: str = ""
    source_url: str = ""
    sha256: str = ""

    @property
    def doc_id(self) -> str:
        """Stable id from the file's content hash (or its name before hashing)."""
        return (self.sha256 or hashlib.sha256(self.file.encode()).hexdigest())[:12]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> list[NoticeEntry]:
    if not path.exists():
        return []
    known = {f.name for f in fields(NoticeEntry)}
    with path.open(encoding="utf-8", newline="") as fh:
        return [
            NoticeEntry(**{k: (v or "").strip() for k, v in row.items() if k in known})
            for row in csv.DictReader(fh)
        ]


def write_manifest(path: Path, entries: list[NoticeEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for entry in sorted(entries, key=lambda e: e.file):
            writer.writerow(asdict(entry))
