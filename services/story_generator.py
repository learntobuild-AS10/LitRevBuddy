from __future__ import annotations

import re
from typing import TYPE_CHECKING

from models.story import PaperStory, ParsedPaper

if TYPE_CHECKING:
    from services.llm_provider import StoryLLMProvider


class StoryGenerationError(RuntimeError):
    pass


SECTION_BUDGETS = {
    "abstract": 7000,
    "introduction": 14000,
    "method": 18000,
    "experiments": 14000,
    "results": 14000,
    "discussion": 8000,
    "limitations": 8000,
    "conclusion": 8000,
}
MAX_CONTEXT_CHARS = 85_000

SYSTEM_PROMPT = """You turn research papers into compact technical story cards for researchers.

Accuracy rules are strict:
1. Use only the supplied metadata and source text. Do not use outside knowledge.
2. Never invent performance numbers, datasets, sample sizes, baselines, architecture components, statistical significance, or limitations.
3. Every card must include a short verbatim evidence span copied exactly from the supplied source text. The application verifies this span.
4. claim_basis must be paper_stated when the card reports an explicit claim, paraphrase when it restates supported source content, or interpretation only for a cautious interpretation anchored in the evidence.
5. If the source does not support a card type, omit it. In particular, abstract-only sources often do not support detailed experiment, results, or limitation cards.
6. Prefer 7-9 cards for full papers and 5-7 cards for abstract-only sources, but never pad the story.
7. Keep each card concise: one short body paragraph and no more than four bullets. Preserve exact numeric values when used.
8. Set provenance_verified=false for every card and flashcard. The application will verify evidence after generation.
9. The story must help a technically literate reader understand the problem, gap, central idea, mechanism, evidence, and limitations where those are actually supported.
10. Do not write citations, markdown tables, or long prose blocks.

Recommended card order: hook, problem, gap, core idea, method/how it works, experiment, results, limitations, takeaway. Omit unsupported stages rather than guessing.
"""


def build_source_context(parsed: ParsedPaper) -> str:
    source = parsed.source
    header = [
        "<<<METADATA>>>",
        f"Title: {source.title}",
        f"Authors: {source.authors}",
        f"Venue: {source.venue}",
        f"Year: {source.year if source.year is not None else ''}",
        f"Paper URL: {source.paper_url}",
        f"PDF URL: {source.pdf_url}",
        f"Source quality: {parsed.source_quality}",
    ]
    pieces = ["\n".join(header)]

    if parsed.source_quality == "abstract":
        pieces.append(f"<<<SECTION: ABSTRACT>>>\n{parsed.sections.get('abstract', parsed.full_text)[:12000]}")
        return "\n\n".join(pieces)

    used = sum(len(piece) for piece in pieces)
    included = set()
    for section, budget in SECTION_BUDGETS.items():
        text = parsed.sections.get(section, "").strip()
        if not text:
            continue
        chunk = text[:budget]
        if used + len(chunk) > MAX_CONTEXT_CHARS:
            chunk = chunk[: max(0, MAX_CONTEXT_CHARS - used)]
        if not chunk:
            break
        pieces.append(f"<<<SECTION: {section.upper()}>>>\n{chunk}")
        included.add(section)
        used += len(chunk)
        if used >= MAX_CONTEXT_CHARS:
            break

    if used < MAX_CONTEXT_CHARS and len(included) < 3:
        remaining = MAX_CONTEXT_CHARS - used
        pieces.append(f"<<<SECTION: EXTRACTED FULL TEXT>>>\n{parsed.full_text[:remaining]}")

    return "\n\n".join(pieces)


def _normalize_for_match(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def evidence_is_supported(evidence: str, source_context: str) -> bool:
    evidence_norm = _normalize_for_match(evidence)
    if len(evidence_norm) < 12:
        return False
    return evidence_norm in _normalize_for_match(source_context)


def _numbers_supported(text: str, source_context: str) -> bool:
    source_norm = _normalize_for_match(source_context)
    numbers = re.findall(r"(?<!\w)[+-]?(?:\d+(?:\.\d+)?%?|\.\d+%?)(?!\w)", text or "")
    return all(number.casefold() in source_norm for number in numbers)



def _locate_evidence_section(evidence: str, parsed: ParsedPaper) -> str:
    evidence_norm = _normalize_for_match(evidence)
    if not evidence_norm:
        return "source"

    for section, text in parsed.sections.items():
        if evidence_norm in _normalize_for_match(text):
            return section

    if evidence_norm in _normalize_for_match(parsed.full_text):
        return "full_text"

    metadata_values = [
        parsed.source.title,
        parsed.source.authors,
        parsed.source.venue,
        str(parsed.source.year or ""),
    ]
    if any(evidence_norm in _normalize_for_match(value) for value in metadata_values if value):
        return "metadata"

    return "source"


def validate_story(story: PaperStory, parsed: ParsedPaper, source_context: str) -> PaperStory:
    source = parsed.source

    story.paper_id = source.paper_id
    story.title = source.title
    story.authors = source.authors
    story.venue = source.venue
    story.year = source.year
    story.paper_url = source.paper_url
    story.pdf_url = source.pdf_url
    story.source_quality = parsed.source_quality
    story.generated_from = sorted(parsed.sections.keys()) if parsed.sections else ["full_text"]

    verified_cards = []
    for card in story.cards[:9]:
        combined = " ".join([card.headline, card.body, *card.bullets])
        evidence_ok = evidence_is_supported(card.evidence, source_context)
        numbers_ok = _numbers_supported(combined, source_context)
        card.provenance_verified = evidence_ok and numbers_ok
        if card.provenance_verified:
            card.source_section = _locate_evidence_section(card.evidence, parsed)
            card.bullets = card.bullets[:4]
            card.body = card.body[:700]
            card.headline = card.headline[:180]
            verified_cards.append(card)

    story.cards = verified_cards

    verified_flashcards = []
    for flashcard in story.flashcards[:5]:
        evidence_ok = evidence_is_supported(flashcard.evidence, source_context)
        numbers_ok = _numbers_supported(flashcard.answer, source_context)
        flashcard.provenance_verified = evidence_ok and numbers_ok
        if flashcard.provenance_verified:
            flashcard.source_section = _locate_evidence_section(flashcard.evidence, parsed)
            flashcard.question = flashcard.question[:240]
            flashcard.answer = flashcard.answer[:700]
            verified_flashcards.append(flashcard)
    story.flashcards = verified_flashcards

    story.key_concepts = [concept[:120] for concept in story.key_concepts[:8] if concept.strip()]
    story.short_title = story.short_title[:100] or source.title[:100]
    story.one_line_summary = story.one_line_summary[:320]
    if story.one_line_summary and not _numbers_supported(story.one_line_summary, source_context):
        story.one_line_summary = story.cards[0].body[:320] if story.cards else source.title[:320]

    minimum_cards = 3 if parsed.source_quality == "abstract" else 4
    if len(story.cards) < minimum_cards:
        raise StoryGenerationError(
            "Too few generated cards passed provenance checks. Try the full paper, or regenerate with a cleaner source."
        )
    return story


def generate_story(parsed: ParsedPaper, provider: "StoryLLMProvider") -> PaperStory:
    source_context = build_source_context(parsed)
    mode_note = (
        "This is an abstract-only source. Do not infer hidden method details, datasets, numerical results, or limitations."
        if parsed.source_quality == "abstract"
        else "This is extracted full-paper text. Use the supplied sections, but still omit anything not supported by the text."
    )
    user_prompt = f"{mode_note}\n\nCreate the PaperStory object from this source:\n\n{source_context}"
    story = provider.generate(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
    return validate_story(story, parsed, source_context)
