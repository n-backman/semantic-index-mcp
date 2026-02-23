from __future__ import annotations

import unittest

from common import SCRIPTS_DIR

from semantic_index.resolve_calls import resolve_calls
from semantic_index.schemas import (
    EDGE_RESOLUTION_AMBIGUOUS,
    EDGE_RESOLUTION_EXTERNAL,
    EDGE_RESOLUTION_RESOLVED,
)


class ResolverTests(unittest.TestCase):
    def test_unique_ambiguous_external_resolution(self) -> None:
        symbols = [
            {
                "id": "/tmp/A.swift::A::tick()::L1",
                "name": "tick",
                "arity": 0,
                "container": "A",
                "kind": "function",
                "file": "/tmp/A.swift",
            },
            {
                "id": "/tmp/B.swift::B::tick()::L1",
                "name": "tick",
                "arity": 0,
                "container": "B",
                "kind": "function",
                "file": "/tmp/B.swift",
            },
            {
                "id": "/tmp/C.swift::C::run()::L1",
                "name": "run",
                "arity": 0,
                "container": "C",
                "kind": "function",
                "file": "/tmp/C.swift",
            },
        ]

        calls = [
            {
                "source_symbol_id": "/tmp/C.swift::C::run()::L1",
                "callee_name": "tick",
                "qualifier": "A",
                "arity": 0,
                "line": 10,
            },
            {
                "source_symbol_id": "/tmp/C.swift::C::run()::L1",
                "callee_name": "tick",
                "qualifier": None,
                "arity": 0,
                "line": 11,
            },
            {
                "source_symbol_id": "/tmp/C.swift::C::run()::L1",
                "callee_name": "missing",
                "qualifier": None,
                "arity": 1,
                "line": 12,
            },
        ]

        edges = resolve_calls(symbols, calls)
        self.assertEqual(edges[0]["resolution"], EDGE_RESOLUTION_AMBIGUOUS)
        self.assertEqual(edges[1]["resolution"], EDGE_RESOLUTION_EXTERNAL)
        self.assertEqual(edges[2]["resolution"], EDGE_RESOLUTION_RESOLVED)


if __name__ == "__main__":
    unittest.main()
