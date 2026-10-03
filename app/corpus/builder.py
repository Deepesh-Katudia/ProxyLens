"""Turn parsed legal units and schedules into `RegulationChunk` documents."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.corpus.chunking import pack_paragraphs
from app.corpus.tagging import TagMap
from app.corpus.units import LegalUnit, to_paragraphs
from app.schemas.regulation import RegulationChunk, RegulationSource

MIN_CHUNK_WORDS = 5
_DASHES = "\\-\N{EN DASH}"  # hyphen and en dash, for a regex class
_PART_HEADING = re.compile(
    rf"^(?:SCHEDULE [IVXL]+\s*:\s*)?PART\s+([IVX]+|[A-Z])\b\s*[:.{_DASHES}]?\s*(.*)$"
)
_SCHEDULE_PREFIX = re.compile(rf"^SCHEDULE\s+[IVXL]+\s*[:{_DASHES}]?\s*", re.IGNORECASE)
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}


@dataclass(frozen=True)
class SourceDoc:
    source: RegulationSource
    short_name: str  # "SEBI LODR 2015"
    unit_label: str  # "Regulation" | "Section"
    id_prefix: str  # "lodr" | "ca"
    key_prefix: str  # "reg" | "s"  (also used for corpus_tags.yaml keys)
    source_url: str
    as_of: str


def roman_to_int(roman: str) -> int:
    total = 0
    values = [_ROMAN[c] for c in roman.upper()]
    for i, value in enumerate(values):
        total += -value if i + 1 < len(values) and value < values[i + 1] else value
    return total


def slice_between(
    lines: Sequence[str],
    start: Callable[[str], bool],
    end: Callable[[str], bool],
) -> list[str]:
    """Lines from the first `start` match (inclusive) up to the next `end` match."""
    for i, line in enumerate(lines):
        if start(line):
            for j in range(i + 1, len(lines)):
                if end(lines[j]):
                    return list(lines[i:j])
            return list(lines[i:])
    raise ValueError("start marker not found")


def _split_ids(base_id: str, texts: list[str]) -> list[str]:
    if len(texts) == 1:
        return [base_id]
    return [f"{base_id}_p{i}" for i in range(1, len(texts) + 1)]


def _make_chunks(
    doc: SourceDoc,
    tags: TagMap,
    *,
    base_id: str,
    citation: str,
    heading: str,
    section_path: list[str],
    paragraphs: Sequence[str],
    tag_keys: Sequence[str],
) -> list[RegulationChunk]:
    texts = [t for t in pack_paragraphs(paragraphs) if len(t.split()) >= MIN_CHUNK_WORDS]
    applies_to = tags.lookup(doc.source, *tag_keys)
    return [
        RegulationChunk(
            id=chunk_id,
            source=doc.source,
            citation=citation,
            heading=heading,
            section_path=section_path,
            text=text,
            applies_to=applies_to,
            source_url=doc.source_url,
            as_of=doc.as_of,
        )
        for chunk_id, text in zip(_split_ids(base_id, texts), texts, strict=True)
    ]


def unit_chunks(
    units: Sequence[LegalUnit],
    doc: SourceDoc,
    tags: TagMap,
    only: set[str] | None = None,
) -> list[RegulationChunk]:
    """One chunk (or several, if long) per sub-unit; `only` filters unit numbers."""
    chunks: list[RegulationChunk] = []
    for unit in units:
        if only is not None and unit.number not in only:
            continue
        unit_key = f"{doc.key_prefix}{unit.number}".lower()
        for sub in unit.subunits:
            label = f"{doc.unit_label} {unit.number}" + (f"({sub.label})" if sub.label else "")
            path = [p for p in (unit.chapter, f"{doc.unit_label} {unit.number}") if p]
            base_id = f"{doc.id_prefix}_{unit_key}"
            keys = [unit_key]
            if sub.label:
                path.append(f"({sub.label})")
                base_id += f"_{sub.label.lower()}"
                keys.insert(0, f"{unit_key}.{sub.label}")
            chunks += _make_chunks(
                doc,
                tags,
                base_id=base_id,
                citation=f"{label}, {doc.short_name}",
                heading=unit.heading,
                section_path=path,
                paragraphs=sub.paragraphs,
                tag_keys=keys,
            )
    return chunks


def _first_caps_line(lines: Sequence[str]) -> str:
    """Fallback schedule title: first all-caps line that isn't a cross-reference."""
    return next((s for s in lines if s.isupper() and not s.startswith(("[", "(", "PART"))), "")


def schedule_chunks(
    lines: Sequence[str],
    roman: str,
    doc: SourceDoc,
    tags: TagMap,
) -> list[RegulationChunk]:
    """Chunk a schedule, split by its PART headings when it has them."""
    title = _SCHEDULE_PREFIX.sub("", lines[0]) or _first_caps_line(lines[1:])
    sch_key = f"sch{roman_to_int(roman)}"
    parts: list[tuple[str | None, str, list[str]]] = [(None, title, [])]
    for line in lines[1:]:
        if match := _PART_HEADING.match(line):
            parts.append((match.group(1), match.group(2).strip(), []))
        elif line.isupper() and not any(parts[-1][2]) and parts[-1][0] is not None:
            # Part titles in capitals often wrap onto a second line.
            part, part_title, part_lines = parts[-1]
            parts[-1] = (part, f"{part_title} {line}".strip(), part_lines)
        elif line or parts[-1][2]:
            parts[-1][2].append(line)

    chunks: list[RegulationChunk] = []
    for part, part_title, part_lines in parts:
        name = f"Schedule {roman}" + (f", Part {part}" if part else "")
        key = f"{sch_key}.part{part.lower()}" if part else sch_key
        chunks += _make_chunks(
            doc,
            tags,
            base_id=f"{doc.id_prefix}_{key.replace('.', '_')}",
            citation=f"{name}, {doc.short_name}",
            heading=part_title or title,
            section_path=[f"Schedule {roman}"] + ([f"Part {part}"] if part else []),
            paragraphs=to_paragraphs(part_lines),
            tag_keys=[key, sch_key],
        )
    return chunks
