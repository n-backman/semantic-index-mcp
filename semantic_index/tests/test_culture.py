from __future__ import annotations

import unittest

from common import SCRIPTS_DIR

from semantic_index.classify_culture import classify_file
from semantic_index.schemas import CULTURE_AUDITOR, CULTURE_CITIZEN, CULTURE_LAW, CULTURE_VIEW


class CultureClassifierTests(unittest.TestCase):
    def test_path_based_rules(self) -> None:
        self.assertEqual(classify_file("Sources/UI/Foo.swift", {}), CULTURE_VIEW)
        self.assertEqual(
            classify_file("Tests/FooTests.swift", {}),
            CULTURE_AUDITOR,
        )
        self.assertEqual(
            classify_file("Sources/Config/FooConfig.swift", {}),
            CULTURE_LAW,
        )

    def test_fallback_rules(self) -> None:
        analysis_law = {"types": [{"name": "EconomyConfig"}], "functions": []}
        self.assertEqual(
            classify_file("Sources/Core/Any.swift", analysis_law),
            CULTURE_LAW,
        )

        analysis_auditor = {"types": [{"name": "StoreTests"}], "functions": []}
        self.assertEqual(
            classify_file("other/Store.swift", analysis_auditor),
            CULTURE_AUDITOR,
        )

        analysis_citizen = {"types": [{"name": "Engine"}], "functions": [{"name": "run"}]}
        self.assertEqual(
            classify_file("Sources/Core/Run.swift", analysis_citizen),
            CULTURE_CITIZEN,
        )


if __name__ == "__main__":
    unittest.main()
