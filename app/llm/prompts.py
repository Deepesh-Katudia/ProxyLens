"""Extraction prompt. Shared by the teacher, the student and the SFT export, so all
three see exactly the same input format."""

from app.schemas.resolution import ResolutionType

# Inputs are truncated so prompt + answer fit the student's 4,096-token window.
MAX_ITEM_CHARS = 4000
MAX_STATEMENT_CHARS = 6000
TRUNCATION_MARK = " [...]"

_TYPES = "\n".join(f"- {t.value}" for t in ResolutionType)

EXTRACTION_SYSTEM_PROMPT = f"""You extract structured data from one agenda item of an Indian \
listed company's general-meeting notice (AGM, EGM or postal ballot). You receive the item's \
agenda text and, when present, its Section 102 explanatory statement. Reply with one JSON \
object only.

Fields:
- item_no: the item number printed in the notice.
- title: a short title for the item (max 15 words).
- resolution_type: exactly one of:
{_TYPES}
  Guidance: retirement-by-rotation re-appointments are DIRECTOR_REAPPOINT_ROTATION; appointment or \
re-appointment of an independent director is INDEPENDENT_DIRECTOR_APPOINT; other director \
appointments (executive, non-executive, nominee) are NON_INDEPENDENT_DIRECTOR_APPOINT; pay, \
commission or terms of a managing/whole-time director or manager are MANAGERIAL_REMUNERATION; \
statutory or secretarial auditor appointment is AUDITOR_APPOINT; ratifying cost auditor \
remuneration is AUDITOR_REMUNERATION_COST; preferential issues, QIPs, NCDs and bonus issues are \
CAPITAL_RAISE; Section 180 borrowing, security or asset-sale limits are BORROWING_LIMITS; \
anything else is OTHER.
- is_special_resolution: true only if the item is proposed as a Special Resolution.
- persons: people the resolution is about (not the company secretary signing the notice). \
For each: name, role, age (years), din, is_promoter, tenure_years_proposed, prior_tenure_years \
(years already served in the same capacity), board_attendance_pct (0-100). Use null when not stated.
- amounts: monetary limits or values in the resolution. amount_inr is the value in rupees \
(1 lakh = 100000, 1 crore = 10000000); raw is the text as written.
- counterparty, counterparty_is_related, transaction_nature: for related-party transactions; \
otherwise null.
- duration_years: the period the approval covers, if stated.
- key_facts: up to 5 short factual bullets an analyst would need, copied or closely paraphrased.

Rules: use only the given text; never guess; use null or [] when information is absent."""


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + TRUNCATION_MARK


def build_extraction_input(item_no: int, item_text: str, explanatory_statement: str | None) -> str:
    """The user message: item number, agenda text and the (truncated) statement."""
    parts = [f"AGENDA ITEM No. {item_no}:\n{_truncate(item_text, MAX_ITEM_CHARS)}"]
    if explanatory_statement:
        statement = _truncate(explanatory_statement, MAX_STATEMENT_CHARS)
        parts.append(f"EXPLANATORY STATEMENT:\n{statement}")
    else:
        parts.append("EXPLANATORY STATEMENT:\n(none)")
    return "\n\n".join(parts)


def repair_message(error: str) -> str:
    return (
        "Your previous reply was not valid for the required schema:\n"
        f"{error[:1500]}\n"
        "Reply again with one corrected JSON object only."
    )
