"""Chat-format SFT records (SPEC 7.2 step 7)."""

import json
from typing import Any

from app.llm.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_input
from app.schemas.resolution import ResolutionExtraction


def sft_record(
    item_no: int, item_text: str, explanatory_statement: str | None, target: ResolutionExtraction
) -> dict[str, Any]:
    """system + user (same prompt the teacher saw) + assistant (target JSON)."""
    answer = json.dumps(target.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return {
        "messages": [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_extraction_input(item_no, item_text, explanatory_statement),
            },
            {"role": "assistant", "content": answer},
        ]
    }
