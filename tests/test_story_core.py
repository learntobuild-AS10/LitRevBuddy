import unittest

from models.story import PaperSource, PaperStory, StoryCard, StudyFlashcard
from services.paper_fetcher import normalize_user_url, resolve_pdf_url
from services.paper_parser import extract_sections, parsed_from_abstract
from services.story_generator import build_source_context, evidence_is_supported, validate_story
from utils.caching import story_cache_key


class StoryCoreTests(unittest.TestCase):
    def test_arxiv_and_openreview_pdf_resolution(self):
        self.assertEqual(
            resolve_pdf_url("https://arxiv.org/abs/2401.12345"),
            "https://arxiv.org/pdf/2401.12345.pdf",
        )
        self.assertEqual(
            resolve_pdf_url("https://openreview.net/forum?id=abc123"),
            "https://openreview.net/pdf?id=abc123",
        )

    def test_doi_normalization(self):
        self.assertEqual(
            normalize_user_url("10.1234/example.5678"),
            "https://doi.org/10.1234/example.5678",
        )

    def test_section_extraction(self):
        text = """Abstract
This paper studies a useful problem in enough detail for extraction.

1 Introduction
The introduction explains the motivation and prior gap with several sentences.

3 Method
The method combines two components and explains how they interact in the model.

5 Results
The results report an accuracy of 91.2% on Dataset X under the stated setup.
"""
        sections = extract_sections(text)
        self.assertIn("abstract", sections)
        self.assertIn("introduction", sections)
        self.assertIn("method", sections)
        self.assertIn("results", sections)

    def test_evidence_and_number_validation(self):
        source = PaperSource(
            paper_id="1",
            title="Example Paper",
            authors="A. Author",
            venue="CVPR",
            year=2026,
            abstract="Our method reaches 91.2% accuracy on Dataset X and improves the baseline.",
            source_kind="library",
        )
        parsed = parsed_from_abstract(source)
        context = build_source_context(parsed)
        self.assertTrue(evidence_is_supported("reaches 91.2% accuracy on Dataset X", context))

        valid_card = StoryCard(
            card_type="results",
            eyebrow="Results",
            headline="The method reports 91.2% accuracy",
            body="The paper reports 91.2% accuracy on Dataset X.",
            bullets=[],
            visual_hint="metric",
            source_section="abstract",
            evidence="Our method reaches 91.2% accuracy on Dataset X and improves the baseline.",
            claim_basis="paper_stated",
            provenance_verified=False,
        )
        unsupported_card = StoryCard(
            card_type="results",
            eyebrow="Results",
            headline="The method reports 99.9% accuracy",
            body="The paper reports 99.9% accuracy on Dataset X.",
            bullets=[],
            visual_hint="metric",
            source_section="abstract",
            evidence="Our method reaches 91.2% accuracy on Dataset X and improves the baseline.",
            claim_basis="paper_stated",
            provenance_verified=False,
        )
        story = PaperStory(
            paper_id="wrong",
            title="Wrong",
            short_title="Example",
            authors="Wrong",
            venue="Wrong",
            year=2000,
            paper_url="",
            pdf_url="",
            one_line_summary="A supported summary.",
            cards=[valid_card, valid_card.model_copy(deep=True), valid_card.model_copy(deep=True), unsupported_card],
            key_concepts=["accuracy"],
            flashcards=[StudyFlashcard(
                question="What accuracy is reported?",
                answer="91.2% on Dataset X.",
                source_section="abstract",
                evidence="Our method reaches 91.2% accuracy on Dataset X and improves the baseline.",
                provenance_verified=False,
            )],
            generated_from=["wrong"],
            source_quality="abstract",
        )
        checked = validate_story(story, parsed, context)
        self.assertEqual(len(checked.cards), 3)
        self.assertTrue(all(card.provenance_verified for card in checked.cards))
        self.assertEqual(checked.title, "Example Paper")

    def test_cache_key_changes_with_mode(self):
        a = story_cache_key(source_fingerprint="abc", provider="openai", model="m", mode="abstract")
        b = story_cache_key(source_fingerprint="abc", provider="openai", model="m", mode="full_paper")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
