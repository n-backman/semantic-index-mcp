from __future__ import annotations

import time
import unittest

from common import SCRIPTS_DIR

from semantic_index.query_tools import GraphQueryEngine


class WarmQueryPerfTests(unittest.TestCase):
    def test_warm_queries_under_200ms(self) -> None:
        files = [{"id": "/tmp/f.swift", "culture": "Citizen"}]
        symbols = []
        edges = []
        symbols_by_name: dict[str, list[str]] = {}
        symbols_by_file = {"/tmp/f.swift": []}
        impact_symbols = {}

        for idx in range(600):
            sid = f"S{idx}"
            name = f"func_{idx}"
            symbols.append(
                {
                    "id": sid,
                    "name": name,
                    "signature": f"{name}()",
                    "kind": "function",
                    "file": "/tmp/f.swift",
                    "line": idx + 1,
                    "visibility": "internal",
                }
            )
            symbols_by_name.setdefault(name, []).append(sid)
            symbols_by_file["/tmp/f.swift"].append(sid)
            impact_symbols[sid] = {
                "direct_callers": 1,
                "depth2_callers": 2,
                "fan_out": 1,
                "score": float(idx % 17),
                "unresolved_count": 0,
                "unresolved_min_confidence": 1.0,
            }
            if idx > 0:
                edges.append(
                    {
                        "source": f"S{idx-1}",
                        "target": sid,
                        "resolution": "resolved",
                        "target_name": name,
                    }
                )

        graph = {
            "files": files,
            "symbols": symbols,
            "edges_calls": edges,
            "indexes": {
                "symbols_by_name": symbols_by_name,
                "symbols_by_file": symbols_by_file,
            },
            "impact": {"symbols": impact_symbols, "files": {"/tmp/f.swift": {}}},
        }

        engine = GraphQueryEngine(graph)

        start = time.perf_counter()
        for _ in range(150):
            engine.find_symbol("func_455")
            engine.impact_radius("S455", "symbol", depth=2)
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / 300.0) * 1000.0

        self.assertLess(avg_ms, 200.0, f"average query latency too high: {avg_ms:.2f}ms")


if __name__ == "__main__":
    unittest.main()
