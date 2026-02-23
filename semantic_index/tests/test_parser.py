from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common import SCRIPTS_DIR, write

from semantic_index.ast_parser import analyze_file


class ParserFixtureTests(unittest.TestCase):
    def test_extracts_decls_calls_and_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            swift_file = root / "Sample.swift"
            write(
                swift_file,
                """
import Foundation

struct SampleEngine {
    var counter: Int = 0

    mutating func bump(value: Int) {
        counter = counter + value
        helper(amount: value)
    }

    func helper(amount: Int) {
        _ = amount + 1
    }
}
""".strip()
                + "\n",
            )

            analysis = analyze_file(swift_file)

            function_names = {item["name"] for item in analysis["functions"]}
            self.assertIn("bump", function_names)
            self.assertIn("helper", function_names)

            variable_names = {item["name"] for item in analysis["variables"]}
            self.assertIn("counter", variable_names)

            call_names = {item["callee_name"] for item in analysis["calls"]}
            self.assertIn("helper", call_names)

            mutation_names = {item["target_name"] for item in analysis["mutations"]}
            self.assertIn("counter", mutation_names)


if __name__ == "__main__":
    unittest.main()
