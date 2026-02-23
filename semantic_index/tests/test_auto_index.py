from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from common import create_minimal_swift_repo, write

from semantic_index.auto_index import AutoIndexManager
from semantic_index.graph_store import graph_path


class AutoIndexTests(unittest.TestCase):
    def test_bootstrap_builds_graph_and_refreshes_on_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as state:
            root = Path(tmp)
            create_minimal_swift_repo(root)

            old_state = os.environ.get("SEMANTIC_INDEX_STATE_DIR")
            os.environ["SEMANTIC_INDEX_STATE_DIR"] = state
            manager: AutoIndexManager | None = None
            try:
                manager = AutoIndexManager(root, watch=False)
                manager.start(bootstrap=True)
                path = graph_path(root)
                self.assertTrue(path.exists())
                before = path.read_text(encoding="utf-8")

                target = root / "Sources/Core/CitizenLogic.swift"
                content = target.read_text(encoding="utf-8")
                write(target, content + "\n// watcher edit\n")

                refreshed = manager.refresh_if_needed()
                self.assertTrue(refreshed)
                after = path.read_text(encoding="utf-8")
                self.assertNotEqual(before, after)
            finally:
                if manager is not None:
                    manager.stop()
                if old_state is None:
                    os.environ.pop("SEMANTIC_INDEX_STATE_DIR", None)
                else:
                    os.environ["SEMANTIC_INDEX_STATE_DIR"] = old_state
