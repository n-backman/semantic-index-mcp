from __future__ import annotations

import unittest

from semantic_index.query_tools import GraphQueryEngine
from semantic_index.schemas import MAX_TOOL_NODES


class QueryLimitTests(unittest.TestCase):
    def test_get_callees_caps_large_node_payloads(self) -> None:
        file_id = "/tmp/workspace.swift"
        symbols = [
            {
                "id": "ROOT",
                "name": "root",
                "signature": "root()",
                "kind": "function",
                "file": file_id,
                "line": 1,
                "visibility": "internal",
            }
        ]
        edges = []
        impact = {"symbols": {}, "files": {}}

        for index in range(MAX_TOOL_NODES + 25):
            symbol_id = f"NODE_{index}"
            symbols.append(
                {
                    "id": symbol_id,
                    "name": f"node{index}",
                    "signature": f"node{index}()",
                    "kind": "function",
                    "file": file_id,
                    "line": index + 2,
                    "visibility": "internal",
                }
            )
            edges.append(
                {
                    "source": "ROOT",
                    "target": symbol_id,
                    "target_name": f"node{index}",
                    "target_candidates": [symbol_id],
                    "resolution": "resolved",
                    "confidence": 1.0,
                    "qualifier": None,
                    "arity": 0,
                    "line": index + 2,
                }
            )

        graph = {
            "files": [{"id": file_id, "role": "Citizen"}],
            "symbols": symbols,
            "edges_calls": edges,
            "edges_mutations": [],
            "edges_depends_on": [],
            "impact": impact,
            "indexes": {
                "symbols_by_name": {},
                "symbols_by_file": {file_id: [symbol["id"] for symbol in symbols]},
                "files_by_role": {"Citizen": [file_id]},
            },
        }

        engine = GraphQueryEngine(graph)
        payload = engine.get_callees("ROOT")
        self.assertTrue(payload["truncated"])
        self.assertEqual(len(payload["nodes"]), MAX_TOOL_NODES)


if __name__ == "__main__":
    unittest.main()
