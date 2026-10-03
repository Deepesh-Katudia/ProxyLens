"""Parsed-notice data structures."""

from enum import StrEnum

from pydantic import BaseModel, Field


class MeetingType(StrEnum):
    AGM = "AGM"
    EGM = "EGM"
    POSTAL_BALLOT = "POSTAL_BALLOT"
    UNKNOWN = "UNKNOWN"


class BusinessSection(StrEnum):
    ORDINARY = "ORDINARY"
    SPECIAL = "SPECIAL"


class NoticeItem(BaseModel):
    seq: int = Field(ge=1)  # 1-based position in the notice; unique
    item_no: int  # number printed in the notice; can repeat in odd notices
    section: BusinessSection | None
    text: str  # agenda text: title plus the proposed resolution
    explanatory_statement: str | None = None  # Section 102 statement, if any
    resolution_kind_hint: BusinessSection | None = None  # "as a Special Resolution"

    @property
    def title(self) -> str:
        """First sentence of the item, capped for display."""
        first = self.text.split("\n", 1)[0].strip()
        return first if len(first) <= 200 else first[:197] + "..."


class ParsedNotice(BaseModel):
    meeting_type: MeetingType
    page_count: int
    items: list[NoticeItem]
