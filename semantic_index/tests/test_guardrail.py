from __future__ import annotations

import unittest

from common import SCRIPTS_DIR

from semantic_index.query_tools import GraphQueryEngine


class GuardrailTests(unittest.TestCase):
    def test_law_hard_block_and_fail_closed(self) -> None:
        graph = {
            "files": [
                {"id": "/tmp/law.swift", "culture": "Law"},
                {"id": "/tmp/citizen.swift", "culture": "Citizen"},
            ],
            "symbols": [
                {
                    "id": "LAW",
                    "name": "rate",
                    "signature": "rate()",
                    "kind": "function",
                    "file": "/tmp/law.swift",
                    "line": 1,
                    "visibility": "public",
                },
                {
                    "id": "CIT",
                    "name": "run",
                    "signature": "run()",
                    "kind": "function",
                    "file": "/tmp/citizen.swift",
                    "line": 1,
                    "visibility": "internal",
                },
            ],
            "edges_calls": [],
            "indexes": {"symbols_by_name": {}, "symbols_by_file": {}},
            "impact": {
                "symbols": {
                    "LAW": {
                        "direct_callers": 120,
                        "depth2_callers": 150,
                        "fan_out": 3,
                        "score": 88,
                        "unresolved_count": 0,
                        "unresolved_min_confidence": 1.0,
                    },
                    "CIT": {
                        "direct_callers": 10,
                        "depth2_callers": 20,
                        "fan_out": 4,
                        "score": 12,
                        "unresolved_count": 3,
                        "unresolved_min_confidence": 0.2,
                    },
                },
                "files": {},
            },
        }

        engine = GraphQueryEngine(graph)

        law = engine.refactor_guardrail("LAW")
        self.assertEqual(law["guardrail"], "hard_block_signature_change")
        self.assertTrue(law["hard_block"])

        citizen = engine.refactor_guardrail("CIT")
        self.assertEqual(citizen["guardrail"], "high_risk_manual_review")
        self.assertFalse(citizen["hard_block"])


if __name__ == "__main__":
    unittest.main()
