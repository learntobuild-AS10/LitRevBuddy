from __future__ import annotations

import re
from difflib import SequenceMatcher
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

CARD_HEADLINE_MAX_WORDS = 14
CARD_BODY_MAX_WORDS = 65
CARD_BULLET_MAX_WORDS = 12
CARD_MAX_BULLETS = 3
SUMMARY_MAX_WORDS = 24
FLASHCARD_QUESTION_MAX_WORDS = 26
FLASHCARD_ANSWER_MAX_WORDS = 40

SYSTEM_PROMPT = """You turn research papers into compact technical story cards for researchers.

Accuracy rules are strict:
1. Use only the supplied metadata and source text. Do not use outside knowledge.
2. Never invent performance numbers, datasets, sample sizes, baselines, architecture components, statistical significance, or limitations.
3. Every card must include a short verbatim evidence span copied exactly from the supplied source text. The application verifies this span.
4. claim_basis must be paper_stated when the card reports an explicit claim, paraphrase when it restates supported source content, or interpretation only for a cautious interpretation anchored in the evidence.
5. If the source does not support a card type, omit it. In particular, abstract-only sources often do not support detailed experiment, results, or limitation cards.
6. Prefer 6-8 cards for full papers and 4-6 cards for abstract-only sources, but never pad the story.
7. Write for a swipe card, not a paper summary. Headline: 6-14 words. Body: 35-65 words, ideally 2-3 sentences. Use at most 3 bullets, each under 12 words.
8. Make every sentence earn its place. Remove setup phrases, repetition, generic praise, and details that do not change the reader's mental model.
9. Keep the one-line summary under 24 words. Flashcard answers should usually be 1-2 short sentences.
10. Preserve exact numeric values when used.
11. Set provenance_verified=false for every card and flashcard. The application will verify evidence after generation.
12. The story must help a technically literate reader understand the problem, gap, central idea, mechanism, evidence, and limitations where those are actually supported.
13. Do not write citations, markdown tables, or long prose blocks.

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


def _clip_words(text: str, max_words: int) -> str:
    words = (text or "").split()
    if len(words) <= max_words:
        return " ".join(words)

    clipped = " ".join(words[:max_words]).rstrip(" ,;:-")
    if clipped and clipped[-1] not in ".!?":
        clipped += "…"
    return clipped


def _normalize_for_match(text: str) -> str:
    text = (text or "").replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = text.replace("–", "-").replace("—", "-")
    return " ".join(text.split()).casefold()


def _match_tokens(text: str) -> list[str]:
    normalized = _normalize_for_match(text)
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?%?", normalized)


def _recover_evidence_span(evidence: str, source_text: str) -> str | None:
    evidence_norm = _normalize_for_match(evidence)
    source_norm = _normalize_for_match(source_text)
    if len(evidence_norm) < 12:
        return None

    if evidence_norm in source_norm:
        return evidence.strip()

    evidence_tokens = _match_tokens(evidence)
    source_tokens = _match_tokens(source_text)
    if len(evidence_tokens) < 5 or len(source_tokens) < len(evidence_tokens):
        return None

    width = len(evidence_tokens)

    # First accept an exact token sequence. This tolerates PDF whitespace,
    # punctuation, and line-wrap differences without weakening provenance.
    for start in range(0, len(source_tokens) - width + 1):
        window = source_tokens[start : start + width]
        if window == evidence_tokens:
            return " ".join(window)

    # Some PDF extractors split/join a token around line breaks. Permit only
    # a very-high-similarity local match and require all numeric claims to
    # remain identical.
    best_ratio = 0.0
    best_window: list[str] | None = None
    for candidate_width in range(max(5, width - 2), min(len(source_tokens), width + 2) + 1):
        for start in range(0, len(source_tokens) - candidate_width + 1):
            window = source_tokens[start : start + candidate_width]
            ratio = SequenceMatcher(None, evidence_tokens, window, autojunk=False).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_window = window

    if best_window is None or best_ratio < 0.94:
        return None

    candidate = " ".join(best_window)
    if not _numbers_supported(evidence, candidate):
        return None
    return candidate


def evidence_is_supported(evidence: str, source_context: str) -> bool:
    return _recover_evidence_span(evidence, source_context) is not None


def _numbers_supported(text: str, source_context: str) -> bool:
    source_norm = _normalize_for_match(source_context)
    numbers = re.findall(r"(?<!\w)[+-]?(?:\d+(?:\.\d+)?%?|\.\d+%?)(?!\w)", text or "")
    return all(number.casefold() in source_norm for number in numbers)



def _locate_evidence_section(evidence: str, parsed: ParsedPaper) -> str:
    if not _normalize_for_match(evidence):
        return "source"

    for section, text in parsed.sections.items():
        if _recover_evidence_span(evidence, text):
            return section

    if _recover_evidence_span(evidence, parsed.full_text):
        return "full_text"

    metadata_values = [
        parsed.source.title,
        parsed.source.authors,
        parsed.source.venue,
        str(parsed.source.year or ""),
    ]
    if any(_recover_evidence_span(evidence, value) for value in metadata_values if value):
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

    generated_card_count = min(len(story.cards), 9)
    verified_cards = []
    for card in story.cards[:9]:
        combined = " ".join([card.headline, card.body, *card.bullets])
        recovered_evidence = _recover_evidence_span(card.evidence, source_context)
        evidence_ok = recovered_evidence is not None
        numbers_ok = _numbers_supported(combined, source_context)
        card.provenance_verified = evidence_ok and numbers_ok
        if card.provenance_verified:
            card.evidence = recovered_evidence or card.evidence
            card.source_section = _locate_evidence_section(card.evidence, parsed)
            card.headline = _clip_words(card.headline, CARD_HEADLINE_MAX_WORDS)
            card.body = _clip_words(card.body, CARD_BODY_MAX_WORDS)
            card.bullets = [
                _clip_words(bullet, CARD_BULLET_MAX_WORDS)
                for bullet in card.bullets[:CARD_MAX_BULLETS]
                if bullet.strip()
            ]
            verified_cards.append(card)

    story.cards = verified_cards

    verified_flashcards = []
    for flashcard in story.flashcards[:5]:
        recovered_evidence = _recover_evidence_span(flashcard.evidence, source_context)
        evidence_ok = recovered_evidence is not None
        numbers_ok = _numbers_supported(flashcard.answer, source_context)
        flashcard.provenance_verified = evidence_ok and numbers_ok
        if flashcard.provenance_verified:
            flashcard.evidence = recovered_evidence or flashcard.evidence
            flashcard.source_section = _locate_evidence_section(flashcard.evidence, parsed)
            flashcard.question = _clip_words(
                flashcard.question,
                FLASHCARD_QUESTION_MAX_WORDS,
            )
            flashcard.answer = _clip_words(
                flashcard.answer,
                FLASHCARD_ANSWER_MAX_WORDS,
            )
            verified_flashcards.append(flashcard)
    story.flashcards = verified_flashcards

    story.key_concepts = [concept[:120] for concept in story.key_concepts[:8] if concept.strip()]
    story.short_title = _clip_words(story.short_title, 12) or _clip_words(source.title, 12)
    story.one_line_summary = _clip_words(story.one_line_summary, SUMMARY_MAX_WORDS)
    if story.one_line_summary and not _numbers_supported(story.one_line_summary, source_context):
        story.one_line_summary = (
            _clip_words(story.cards[0].body, SUMMARY_MAX_WORDS)
            if story.cards
            else _clip_words(source.title, SUMMARY_MAX_WORDS)
        )

    minimum_cards = 2
    if len(story.cards) < minimum_cards:
        raise StoryGenerationError(
            f"Only {len(story.cards)} of {generated_card_count} generated cards could be verified against the source. "
            "Try Quick story, regenerate, or use a cleaner PDF."
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
