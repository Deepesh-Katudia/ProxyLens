"""Map legal units to the resolution types they govern (`config/corpus_tags.yaml`)."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.schemas.regulation import RegulationSource
from app.schemas.resolution import ResolutionType

DEFAULT_TAGS_PATH = Path("config/corpus_tags.yaml")


@dataclass(frozen=True)
class TagMap:
    by_source: Mapping[RegulationSource, Mapping[str, tuple[ResolutionType, ...]]]

    def lookup(self, source: RegulationSource, *keys: str) -> list[ResolutionType]:
        """Tags for the first key that is mapped; pass keys most-specific first."""
        table = self.by_source.get(source, {})
        for key in keys:
            if key.lower() in table:
                return list(table[key.lower()])
        return []


def load_tag_map(path: Path = DEFAULT_TAGS_PATH) -> TagMap:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    by_source: dict[RegulationSource, dict[str, tuple[ResolutionType, ...]]] = {}
    for source in RegulationSource:
        entries = raw.get(source.value) or {}
        by_source[source] = {
            str(key).lower(): tuple(ResolutionType(t) for t in types)
            for key, types in entries.items()
        }
    return TagMap(by_source)
