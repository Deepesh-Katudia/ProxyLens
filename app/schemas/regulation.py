"""Regulation corpus models (SPEC 5, `regulations` collection)."""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.resolution import ResolutionType


class RegulationSource(StrEnum):
    SEBI_LODR_2015 = "SEBI_LODR_2015"
    COMPANIES_ACT_2013 = "COMPANIES_ACT_2013"
    HOUSE_POLICY = "HOUSE_POLICY"


class RegulationChunk(BaseModel):
    """One retrievable legal unit (or a slice of a long one)."""

    id: str = Field(alias="_id")
    source: RegulationSource
    citation: str
    heading: str = ""
    section_path: list[str]
    text: str
    applies_to: list[ResolutionType] = Field(default_factory=list)
    source_url: str
    as_of: str
    notes: str | None = None  # caveats shown with the chunk, e.g. pre-amendment text
    embedding: list[float] | None = None

    model_config = {"populate_by_name": True}

    def embedding_text(self) -> str:
        """Text fed to the embedder: citation and heading give the chunk context."""
        header = f"{self.citation}. {self.heading}".strip(". ")
        return f"{header}\n{self.text}"


class RegulationHit(BaseModel):
    """A retrieved chunk with its score, as returned by the search API."""

    id: str
    source: RegulationSource
    citation: str
    heading: str
    text: str
    applies_to: list[ResolutionType]
    source_url: str
    notes: str | None = None
    score: float
