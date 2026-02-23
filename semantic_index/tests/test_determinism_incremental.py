from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common import create_minimal_swift_repo, write

from semantic_index.graph_store import graph_path
from semantic_index.indexer import SemanticIndexer


class DeterminismAndIncrementalTests(unittest.TestCase):
    def test_graph_output_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_minimal_swift_repo(root)

            indexer = SemanticIndexer(root)
            indexer.build_full()
            first = graph_path(root).read_text(encoding="utf-8")

            indexer.build_full()
            second = graph_path(root).read_text(encoding="utf-8")

            self.assertEqual(first, second)

    def test_incremental_refresh_reuses_unchanged_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_minimal_swift_repo(root)

            indexer = SemanticIndexer(root)
            _, full_stats = indexer.build_full()
            self.assertGreater(full_stats.files_reparsed, 0)

            target = root / "Sources/Core/CitizenLogic.swift"
            content = target.read_text(encoding="utf-8")
            write(target, content + "\n// edit\n")

            _, refresh_stats = indexer.build_incremental()
            self.assertGreaterEqual(refresh_stats.files_reparsed, 1)
            self.assertGreaterEqual(refresh_stats.files_reused, 1)


if __name__ == "__main__":
    unittest.main()
