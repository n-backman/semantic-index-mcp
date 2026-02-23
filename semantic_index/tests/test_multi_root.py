from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from common import create_minimal_swift_repo, write

from semantic_index.graph_store import graph_path
from semantic_index.indexer import SemanticIndexer, discover_swift_files
from semantic_index.query_tools import GraphQueryEngine


class MultiRootIndexTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks required")
    def test_discover_swift_files_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as root_tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(root_tmp)
            outside = Path(outside_tmp)
            create_minimal_swift_repo(root)
            write(
                outside / "Secret.swift",
                """
import Foundation

struct Secret {
    func leak() {}
}
""".strip()
                + "\n",
            )

            link_path = root / "Sources/Core/Escape.swift"
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(outside / "Secret.swift")

            discovered = discover_swift_files(root)
            indexed_paths = {path for _rel, path in discovered}
            self.assertNotIn((outside / "Secret.swift").resolve(), indexed_paths)

    def test_build_indexes_sibling_roots_into_one_graph(self) -> None:
        with tempfile.TemporaryDirectory() as primary_tmp, tempfile.TemporaryDirectory() as sibling_tmp:
            primary = Path(primary_tmp)
            sibling = Path(sibling_tmp)

            create_minimal_swift_repo(primary)
            create_minimal_swift_repo(sibling)
            write(
                sibling / "Sources/Core/SiblingLogic.swift",
                """
import Foundation

struct SiblingLogic {
    func relay() {
        helper(value: 7)
    }
}
""".strip()
                + "\n",
            )

            graph, stats = SemanticIndexer(primary, [sibling]).build_full()
            self.assertGreaterEqual(stats.files_total, 5)

            meta = graph.get("meta", {})
            self.assertEqual(meta.get("repo_root"), str(primary.resolve()))
            self.assertEqual(
                meta.get("workspace_roots"),
                [str(primary.resolve()), str(sibling.resolve())],
            )

            file_paths = {item["path"] for item in graph.get("files", [])}
            self.assertIn(f"{primary.name}/Sources/Core/CitizenLogic.swift", file_paths)
            self.assertIn(f"{sibling.name}/Sources/Core/SiblingLogic.swift", file_paths)

            loaded = graph_path(primary).read_text(encoding="utf-8")
            self.assertIn(f"{sibling.name}/Sources/Core/SiblingLogic.swift", loaded)

            engine = GraphQueryEngine(graph)
            result = engine.find_symbol("relay")
            match_files = {item["file"] for item in result["matches"]}
            self.assertIn(str((sibling / "Sources/Core/SiblingLogic.swift").resolve()), match_files)

    def test_incremental_refresh_detects_changes_in_sibling_root(self) -> None:
        with tempfile.TemporaryDirectory() as primary_tmp, tempfile.TemporaryDirectory() as sibling_tmp:
            primary = Path(primary_tmp)
            sibling = Path(sibling_tmp)

            create_minimal_swift_repo(primary)
            create_minimal_swift_repo(sibling)

            indexer = SemanticIndexer(primary, [sibling])
            _, full_stats = indexer.build_full()
            self.assertGreater(full_stats.files_reparsed, 0)

            target = sibling / "Sources/Core/CitizenLogic.swift"
            content = target.read_text(encoding="utf-8")
            write(target, content + "\n// sibling edit\n")

            _, refresh_stats = indexer.build_incremental()
            self.assertGreaterEqual(refresh_stats.files_reparsed, 1)
            self.assertGreaterEqual(refresh_stats.files_reused, 1)


if __name__ == "__main__":
    unittest.main()
