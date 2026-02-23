from __future__ import annotations

import os
import unittest
from pathlib import Path

from common import SCRIPTS_DIR

from semantic_index.indexer import SemanticIndexer


@unittest.skipUnless(
    os.environ.get("SEMANTIC_INDEX_REPO_SMOKE") == "1",
    "Set SEMANTIC_INDEX_REPO_SMOKE=1 to run repo-level SLA check.",
)
class RepoSmokeTests(unittest.TestCase):
    def test_full_build_under_60s(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        _, stats = SemanticIndexer(repo_root).build_full()
        self.assertLessEqual(
            stats.duration_ms,
            60_000,
            f"full build exceeded SLA: {stats.duration_ms}ms",
        )


if __name__ == "__main__":
    unittest.main()
