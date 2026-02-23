from __future__ import annotations

import unittest

from common import SCRIPTS_DIR

from semantic_index.query_tools import GraphQueryEngine


class PreEditCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = {
            "files": [
                {"id": "/tmp/core.swift", "role": "Citizen"},
                {"id": "/tmp/law.swift", "role": "Law"},
            ],
            "symbols": [
                {
                    "id": "A",
                    "name": "run",
                    "signature": "run()",
                    "kind": "function",
                    "file": "/tmp/core.swift",
                    "line": 10,
                    "container": "Worker",
                    "visibility": "internal",
                },
                {
                    "id": "B",
                    "name": "caller",
                    "signature": "caller()",
                    "kind": "function",
                    "file": "/tmp/core.swift",
                    "line": 20,
                    "container": "Worker",
                    "visibility": "internal",
                },
                {
                    "id": "C",
                    "name": "dispatch",
                    "signature": "dispatch()",
                    "kind": "function",
                    "file": "/tmp/core.swift",
                    "line": 30,
                    "container": "GameStore",
                    "visibility": "internal",
                },
                {
                    "id": "D",
                    "name": "dispatch",
                    "signature": "dispatch()",
                    "kind": "function",
                    "file": "/tmp/law.swift",
                    "line": 40,
                    "container": "OtherStore",
                    "visibility": "public",
                },
            ],
            "edges_calls": [
                {
                    "source": "B",
                    "target": "A",
                    "resolution": "resolved",
                    "target_name": "run",
                },
                {
                    "source": "B",
                    "target_candidates": ["A"],
                    "resolution": "ambiguous",
                    "target_name": "run",
                },
            ],
            "indexes": {
                "symbols_by_name": {
                    "run": ["A"],
                    "caller": ["B"],
                    "dispatch": ["C", "D"],
                },
                "symbols_by_file": {
                    "/tmp/core.swift": ["A", "B", "C"],
                    "/tmp/law.swift": ["D"],
                },
            },
            "impact": {
                "symbols": {
                    "A": {
                        "direct_callers": 1,
                        "depth2_callers": 1,
                        "fan_out": 0,
                        "score": 7.0,
                        "unresolved_count": 0,
                        "unresolved_min_confidence": 1.0,
                    },
                    "B": {
                        "direct_callers": 0,
                        "depth2_callers": 0,
                        "fan_out": 1,
                        "score": 4.0,
                        "unresolved_count": 0,
                        "unresolved_min_confidence": 1.0,
                    },
                    "C": {
                        "direct_callers": 0,
                        "depth2_callers": 0,
                        "fan_out": 0,
                        "score": 3.0,
                        "unresolved_count": 0,
                        "unresolved_min_confidence": 1.0,
                    },
                    "D": {
                        "direct_callers": 0,
                        "depth2_callers": 0,
                        "fan_out": 0,
                        "score": 5.0,
                        "unresolved_count": 0,
                        "unresolved_min_confidence": 1.0,
                    },
                },
                "files": {},
            },
        }

    def test_resolved_combines_guardrail_impact_and_callers(self) -> None:
        engine = GraphQueryEngine(self.graph)

        result = engine.pre_edit_check(query="run")

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["symbol"]["id"], "A")
        self.assertIn("decision", result["guardrail"])
        self.assertEqual(result["callers"]["resolved_edges"], 1)
        self.assertEqual(result["callers"]["ambiguous_edges"], 1)
        self.assertIn("/tmp/core.swift", result["impact"]["files_touched"])
        self.assertEqual(result["impact"]["node_count"], len(result["impact"]["top_nodes"]))

    def test_ambiguous_when_top_match_ties(self) -> None:
        engine = GraphQueryEngine(self.graph)

        result = engine.pre_edit_check(query="dispatch")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["candidates"]), 2)

    def test_resolves_container_qualified_query(self) -> None:
        engine = GraphQueryEngine(self.graph)

        result = engine.pre_edit_check(query="GameStore.dispatch")

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["symbol"]["id"], "C")

    def test_no_match(self) -> None:
        engine = GraphQueryEngine(self.graph)

        result = engine.pre_edit_check(query="missing")

        self.assertEqual(result["status"], "no_match")


if __name__ == "__main__":
    unittest.main()
