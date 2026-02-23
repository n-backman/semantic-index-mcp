from __future__ import annotations

import unittest

from common import SCRIPTS_DIR

from semantic_index.impact import compute_impact


class ImpactTests(unittest.TestCase):
    def test_depth2_and_scores(self) -> None:
        symbols = [
            {
                "id": "A",
                "file": "/tmp/law.swift",
                "visibility": "public",
                "kind": "function",
            },
            {
                "id": "B",
                "file": "/tmp/citizen.swift",
                "visibility": "internal",
                "kind": "function",
            },
            {
                "id": "C",
                "file": "/tmp/citizen.swift",
                "visibility": "internal",
                "kind": "function",
            },
        ]
        culture_by_file = {
            "/tmp/law.swift": "Law",
            "/tmp/citizen.swift": "Citizen",
        }
        edges_calls = [
            {"source": "B", "target": "A", "resolution": "resolved", "confidence": 1.0},
            {"source": "C", "target": "B", "resolution": "resolved", "confidence": 1.0},
        ]
        edges_mutations = [
            {"source": "A", "target_name": "x"},
            {"source": "A", "target_name": "y"},
        ]

        impact = compute_impact(symbols, edges_calls, edges_mutations, culture_by_file)
        metrics_a = impact["symbols"]["A"]

        self.assertEqual(metrics_a["direct_callers"], 1)
        self.assertEqual(metrics_a["depth2_callers"], 2)
        self.assertGreater(metrics_a["score"], 0)


if __name__ == "__main__":
    unittest.main()
