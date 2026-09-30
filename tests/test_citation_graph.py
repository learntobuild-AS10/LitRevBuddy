import unittest

from scripts.build_citation_graph import select_shared_references


class CitationGraphTests(unittest.TestCase):
    def test_shared_reference_selection_prefers_common_references(self):
        references = {
            1: [
                {"citedPaper": {"paperId": "A", "title": "Shared A", "citationCount": 100}},
                {"citedPaper": {"paperId": "B", "title": "Unique B", "citationCount": 500}},
            ],
            2: [
                {"citedPaper": {"paperId": "A", "title": "Shared A", "citationCount": 100}},
                {"citedPaper": {"paperId": "C", "title": "Shared C", "citationCount": 50}},
            ],
            3: [
                {"citedPaper": {"paperId": "C", "title": "Shared C", "citationCount": 50}},
            ],
        }

        selected = select_shared_references(
            references,
            seed_s2_ids=set(),
            min_seed_count=2,
            max_external_nodes=10,
        )

        self.assertEqual([item["paper_id"] for item in selected], ["A", "C"])
        self.assertEqual(selected[0]["seed_count"], 2)
        self.assertEqual(selected[1]["seed_count"], 2)

    def test_seed_papers_are_not_readded_as_external_references(self):
        references = {
            1: [{"citedPaper": {"paperId": "SEED", "title": "Existing seed", "citationCount": 10}}],
            2: [{"citedPaper": {"paperId": "SEED", "title": "Existing seed", "citationCount": 10}}],
        }

        selected = select_shared_references(
            references,
            seed_s2_ids={"SEED"},
            min_seed_count=2,
            max_external_nodes=10,
        )

        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
