"""Pack legal-unit paragraphs into chunks that fit the embedding budget.

SPEC 5: chunk by legal unit, max ~400 tokens; split longer units with overlap
and keep the same citation. Words are a cheap proxy for tokens: legal English
runs about 1.3 BGE tokens per word, so 280 words stays under 400 tokens.
"""

from collections.abc import Sequence

MAX_WORDS = 280
OVERLAP_WORDS = 40


def _windows(words: list[str], max_words: int, overlap: int) -> list[str]:
    step = max_words - overlap
    out: list[str] = []
    for start in range(0, len(words), step):
        out.append(" ".join(words[start : start + max_words]))
        if start + max_words >= len(words):
            break
    return out


def pack_paragraphs(
    paragraphs: Sequence[str],
    max_words: int = MAX_WORDS,
    overlap: int = OVERLAP_WORDS,
) -> list[str]:
    """Greedily pack whole paragraphs; window any single paragraph that is too long."""
    if overlap >= max_words:
        raise ValueError("overlap must be smaller than max_words")
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    def flush() -> None:
        nonlocal current, current_words
        if current:
            chunks.append("\n".join(current))
        current, current_words = [], 0

    for para in paragraphs:
        words = para.split()
        if len(words) > max_words:
            flush()
            chunks.extend(_windows(words, max_words, overlap))
            continue
        if current_words + len(words) > max_words:
            flush()
        current.append(para)
        current_words += len(words)
    flush()
    return chunks
