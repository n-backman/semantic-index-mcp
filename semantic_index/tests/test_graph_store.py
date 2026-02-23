from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from semantic_index.graph_store import graph_path, load_graph, save_graph, semantic_index_dir


class GraphStoreTests(unittest.TestCase):
    def test_external_state_dir_is_namespaced_per_repo(self) -> None:
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as state_tmp:
            repo_root = Path(repo_tmp)
            state_root = Path(state_tmp)
            old_state = os.environ.get("SEMANTIC_INDEX_STATE_DIR")
            old_key = os.environ.get("SEMANTIC_INDEX_REPO_KEY")
            os.environ["SEMANTIC_INDEX_STATE_DIR"] = str(state_root)
            os.environ["SEMANTIC_INDEX_REPO_KEY"] = "sample-repo"
            try:
                sample = {
                    "meta": {"schema_version": "2.0.0"},
                    "files": [],
                    "symbols": [],
                    "edges_calls": [],
                    "edges_mutations": [],
                    "edges_depends_on": [],
                    "impact": {"symbols": {}, "files": {}},
                    "indexes": {},
                }
                path = save_graph(repo_root, sample)
                self.assertTrue(path.is_relative_to(state_root.resolve()))
                self.assertEqual(path.parent.name, "sample-repo")
                self.assertEqual(path, graph_path(repo_root))
                self.assertEqual(path.parent, semantic_index_dir(repo_root))
                self.assertEqual(load_graph(repo_root), sample)
            finally:
                if old_state is None:
                    os.environ.pop("SEMANTIC_INDEX_STATE_DIR", None)
                else:
                    os.environ["SEMANTIC_INDEX_STATE_DIR"] = old_state
                if old_key is None:
                    os.environ.pop("SEMANTIC_INDEX_REPO_KEY", None)
                else:
                    os.environ["SEMANTIC_INDEX_REPO_KEY"] = old_key
