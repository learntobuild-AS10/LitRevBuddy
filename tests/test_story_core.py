import unittest

import numpy as np
import requests
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

from models.story import PaperSource, PaperStory, StoryCard, StudyFlashcard
from services.llm_provider import OpenRouterStoryProvider
from services.paper_fetcher import FetchError, _request_with_safe_redirects, fetch_page_metadata, normalize_user_url, resolve_pdf_url
from services.paper_parser import extract_sections, parsed_from_abstract
from services.similarity import clean_text
from services.story_generator import build_source_context, evidence_is_supported, validate_story
from utils.caching import story_cache_key
from scripts.ingest_miccai import extract_authors as extract_miccai_authors


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


    def test_arxiv_page_keeps_metadata_and_pdf_fallback(self):
        html = b"""<html><head>
        <meta name="citation_title" content="Example arXiv Paper">
        <meta name="citation_author" content="A. Author">
        <meta name="citation_abstract" content="A sufficiently useful abstract for a quick story.">
        </head><body></body></html>"""
        response = SimpleNamespace(
            headers={"Content-Type": "text/html"},
            url="https://arxiv.org/abs/2401.12345",
            encoding="utf-8",
            iter_content=lambda chunk_size: [html],
            close=lambda: None,
        )
        with patch("services.paper_fetcher._request_with_safe_redirects", return_value=response):
            source = fetch_page_metadata("https://arxiv.org/abs/2401.12345")

        self.assertEqual(source.title, "Example arXiv Paper")
        self.assertEqual(source.authors, "A. Author")
        self.assertIn("useful abstract", source.abstract)
        self.assertEqual(source.pdf_url, "https://arxiv.org/pdf/2401.12345.pdf")

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
        self.assertTrue(all(card.source_section == "abstract" for card in checked.cards))
        self.assertTrue(all(card.source_section == "abstract" for card in checked.flashcards))



    def test_story_validation_enforces_card_length_limits(self):
        source = PaperSource(
            paper_id="2",
            title="Concise Story Test",
            authors="A. Author",
            venue="ICML",
            year=2026,
            abstract="The method uses a compact routing mechanism and reports a supported result.",
            source_kind="library",
        )
        parsed = parsed_from_abstract(source)
        context = build_source_context(parsed)

        verbose_headline = " ".join(["headline"] * 30)
        verbose_body = " ".join(["body"] * 120)
        verbose_bullet = " ".join(["bullet"] * 30)

        card = StoryCard(
            card_type="method",
            eyebrow="Method",
            headline=verbose_headline,
            body=verbose_body,
            bullets=[verbose_bullet, verbose_bullet, verbose_bullet, verbose_bullet],
            visual_hint="mechanism",
            source_section="abstract",
            evidence="The method uses a compact routing mechanism and reports a supported result.",
            claim_basis="paraphrase",
            provenance_verified=False,
        )
        story = PaperStory(
            paper_id="2",
            title="Concise Story Test",
            short_title="Concise Story Test",
            authors="A. Author",
            venue="ICML",
            year=2026,
            paper_url="",
            pdf_url="",
            one_line_summary=" ".join(["summary"] * 60),
            cards=[card, card.model_copy(deep=True), card.model_copy(deep=True)],
            key_concepts=["routing"],
            flashcards=[],
            generated_from=["abstract"],
            source_quality="abstract",
        )

        checked = validate_story(story, parsed, context)

        self.assertEqual(len(checked.cards), 3)
        for checked_card in checked.cards:
            self.assertLessEqual(len(checked_card.headline.split()), 16)
            self.assertLessEqual(len(checked_card.body.split()), 80)
            self.assertLessEqual(len(checked_card.bullets), 3)
            self.assertTrue(all(len(item.split()) <= 16 for item in checked_card.bullets))
        self.assertLessEqual(len(checked.one_line_summary.split()), 32)

    def test_miccai_author_extraction(self):
        html = """
        <html><body>
          <h1>Example MICCAI Paper</h1>
          <h2>Author(s):</h2>
          <div class="authors">
            <span><a href="/author/a">Mi, Jia</a> |</span>
            <span><a href="/author/b">Jiang, Caiwen</a> |</span>
            <span><a href="/author/c">Shen, Dinggang</a> |</span>
          </div>
          <hr>
          <h1>Abstract</h1>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        self.assertEqual(
            extract_miccai_authors(soup),
            "Mi, Jia, Jiang, Caiwen, Shen, Dinggang",
        )


    def test_openrouter_provider_parses_story_json(self):
        story = PaperStory(
            paper_id="1",
            title="Example Paper",
            short_title="Example",
            authors="A. Author",
            venue="CVPR",
            year=2026,
            paper_url="https://example.org/paper",
            pdf_url="https://example.org/paper.pdf",
            one_line_summary="A short source-grounded summary.",
            cards=[
                StoryCard(
                    card_type="takeaway",
                    eyebrow="Takeaway",
                    headline="A supported result",
                    body="The paper reports a supported result.",
                    bullets=[],
                    visual_hint="summary",
                    source_section="abstract",
                    evidence="The paper reports a supported result.",
                    claim_basis="paper_stated",
                    provenance_verified=True,
                )
            ],
            key_concepts=["example"],
            flashcards=[],
            generated_from=["abstract"],
            source_quality="abstract",
        )

        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=f"```json\n{story.model_dump_json()}\n```")
                )
            ]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: response
                )
            )
        )

        with patch("services.llm_provider.OpenAI", return_value=fake_client):
            provider = OpenRouterStoryProvider(api_key="test-key")
            parsed = provider.generate(
                system_prompt="Use only the source.",
                user_prompt="SOURCE: The paper reports a supported result.",
            )

        self.assertEqual(parsed.title, "Example Paper")
        self.assertEqual(parsed.source_quality, "abstract")
        self.assertEqual(len(parsed.cards), 1)


    def test_missing_text_values_do_not_render_as_nan(self):
        self.assertEqual(clean_text(None), "")
        self.assertEqual(clean_text(np.nan), "")

    def test_network_timeout_is_wrapped_as_fetch_error(self):
        with patch("services.paper_fetcher._assert_public_host"), patch(
            "services.paper_fetcher.requests.Session.get",
            side_effect=requests.Timeout("timed out"),
        ):
            with self.assertRaises(FetchError):
                _request_with_safe_redirects("https://example.org/paper", stream=True)

    def test_cache_key_changes_with_mode(self):
        a = story_cache_key(source_fingerprint="abc", provider="openai", model="m", mode="abstract")
        b = story_cache_key(source_fingerprint="abc", provider="openai", model="m", mode="full_paper")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
