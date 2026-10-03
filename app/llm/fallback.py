"""Student-first extraction with teacher fallback (SPEC 5.1).

The student gets one try plus one repair; if it still fails, the teacher is
asked. Whether the fallback fired is recorded, since the fallback rate is an
evaluation metric (SPEC 8).
"""

from dataclasses import dataclass

from app.llm.base import LLMProvider
from app.llm.extraction import ExtractionOutcome, extract


@dataclass(frozen=True)
class FallbackOutcome:
    outcome: ExtractionOutcome  # the result that is used
    used_fallback: bool
    student: ExtractionOutcome  # always the student's attempt, for logging


def extract_with_fallback(
    student: LLMProvider,
    teacher: LLMProvider | None,
    item_no: int,
    item_text: str,
    explanatory_statement: str | None,
) -> FallbackOutcome:
    first = extract(student, item_no, item_text, explanatory_statement)
    if first.valid or teacher is None:
        return FallbackOutcome(first, used_fallback=False, student=first)
    second = extract(teacher, item_no, item_text, explanatory_statement)
    return FallbackOutcome(second, used_fallback=True, student=first)
