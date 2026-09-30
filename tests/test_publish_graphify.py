import json
import unittest

from scripts.publish_graphify import sanitize_graph, validate_no_local_paths


class GraphifyPublisherTests(unittest.TestCase):
    def test_sanitizer_removes_local_paths_and_private_urls(self):
        raw = {
            "directed": True,
            "nodes": [
                {
                    "id": "paper_a",
                    "label": "Paper A",
                    "file_type": "paper",
                    "source_file": "/Users/alice/private/papers/7230__paper-a.pdf",
                    "source_url": "file:///Users/alice/private/papers/paper-a.pdf",
                    "community": 2,
                },
                {
                    "id": "paper_b",
                    "label": "Paper B",
                    "file_type": "paper",
                    "source_file": "/home/alice/paper-b.pdf",
                    "source_url": "https://arxiv.org/abs/1234.5678",
                    "community": 2,
                },
            ],
            "edges": [
                {
                    "source": "paper_a",
                    "target": "paper_b",
                    "relation": "cites",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": "/Users/alice/private/papers/paper-a.pdf",
                }
            ],
        }

        clean = sanitize_graph(raw)
        validate_no_local_paths(clean)

        self.assertEqual(clean["nodes"][0]["source_file"], "7230__paper-a.pdf")
        self.assertEqual(clean["nodes"][0]["litrevbuddy_id"], 7230)
        self.assertEqual(clean["nodes"][0]["source_url"], "")
        self.assertEqual(clean["nodes"][1]["source_file"], "paper-b.pdf")
        self.assertIsNone(clean["nodes"][1]["litrevbuddy_id"])
        self.assertEqual(clean["nodes"][1]["source_url"], "https://arxiv.org/abs/1234.5678")
        self.assertEqual(clean["edges"][0]["source_file"], "7230__paper-a.pdf")
        self.assertEqual(clean["edges"][0]["relation"], "cites")

        encoded = json.dumps(clean)
        self.assertNotIn("/Users/", encoded)
        self.assertNotIn("/home/", encoded)


if __name__ == "__main__":
    unittest.main()
