import unittest

from scripts.export_graphify_corpus import render_paper_markdown


class GraphifyExportTests(unittest.TestCase):
    def test_knowledge_only_export_contains_only_metadata_and_full_abstract(self):
        abstract = "Sentence one. Sentence two. Sentence three."
        body = render_paper_markdown(
            paper_id=7230,
            title="Medic-AD",
            venue="CVPR",
            year="2026",
            authors="A. Author, B. Author",
            topic="clinical/medical imaging",
            abstract=abstract,
            knowledge_only=True,
            direct_refs=["- [1] Other paper"],
            inbound=["- [2] Another paper"],
            external_refs=["- CLIP (2021; cited by 14 seed papers)"],
        )

        self.assertIn("# Medic-AD", body)
        self.assertIn("LitRevBuddy ID: 7230", body)
        self.assertIn("Venue: CVPR", body)
        self.assertIn("Year: 2026", body)
        self.assertIn("Authors: A. Author, B. Author", body)
        self.assertIn("Topic: clinical/medical imaging", body)
        self.assertIn(abstract, body)
        self.assertNotIn("Direct citations", body)
        self.assertNotIn("Cited by", body)
        self.assertNotIn("Shared references", body)
        self.assertNotIn("CLIP", body)
        self.assertNotIn("Other paper", body)

    def test_default_export_still_keeps_citation_context(self):
        body = render_paper_markdown(
            paper_id=1,
            title="Paper",
            venue="Venue",
            year="2025",
            authors="Author",
            topic="Topic",
            abstract="Abstract.",
            knowledge_only=False,
            direct_refs=["- [2] Cited paper"],
            inbound=["- [3] Citing paper"],
            external_refs=["- Shared reference"],
        )

        self.assertIn("## Direct citations to other LitRevBuddy seed papers", body)
        self.assertIn("## Cited by other LitRevBuddy seed papers", body)
        self.assertIn("## Shared references in the citation neighborhood", body)
        self.assertIn("- Shared reference", body)


if __name__ == "__main__":
    unittest.main()
