from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ClaimBasis = Literal["paper_stated", "paraphrase", "interpretation"]
SourceQuality = Literal["abstract", "full_paper"]


class StoryCard(BaseModel):
    card_type: str = Field(description="Short semantic card type, e.g. hook, problem, gap, core_idea, method, experiment, results, limitations, takeaway")
    eyebrow: str
    headline: str
    body: str
    bullets: list[str]
    visual_hint: str
    source_section: str
    evidence: str = Field(description="A short verbatim span copied from the supplied source text that supports this card")
    claim_basis: ClaimBasis
    provenance_verified: bool


class StudyFlashcard(BaseModel):
    question: str
    answer: str
    source_section: str
    evidence: str
    provenance_verified: bool


class PaperStory(BaseModel):
    paper_id: str
    title: str
    short_title: str
    authors: str
    venue: str
    year: int | None
    paper_url: str
    pdf_url: str
    one_line_summary: str
    cards: list[StoryCard]
    key_concepts: list[str]
    flashcards: list[StudyFlashcard]
    generated_from: list[str]
    source_quality: SourceQuality


class PaperSource(BaseModel):
    paper_id: str
    title: str
    authors: str = ""
    venue: str = ""
    year: int | None = None
    paper_url: str = ""
    pdf_url: str = ""
    abstract: str = ""
    source_kind: str = "external"


class ParsedPaper(BaseModel):
    source: PaperSource
    sections: dict[str, str]
    full_text: str
    source_quality: SourceQuality
    extraction_notes: list[str]
