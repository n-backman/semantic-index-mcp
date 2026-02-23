from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def create_minimal_swift_repo(root: Path) -> None:
    write(
        root / "Sources/Config/LawConfig.swift",
        """
import Foundation

struct LawConfig {
    static let cap: Int = 100
}
""".strip()
        + "\n",
    )
    write(
        root / "Sources/Core/CitizenLogic.swift",
        """
import Foundation

struct CitizenLogic {
    var count: Int = 0

    mutating func run() {
        count = count + 1
        helper(value: count)
    }

    func helper(value: Int) {
        _ = value + LawConfig.cap
    }
}
""".strip()
        + "\n",
    )
    write(
        root / "Sources/UI/ViewScreen.swift",
        """
import Foundation

struct ViewScreen {
    func body() {
        var logic = CitizenLogic()
        logic.run()
    }
}
""".strip()
        + "\n",
    )
    write(
        root / "Tests/CitizenLogicTests.swift",
        """
import Foundation

struct CitizenLogicTests {
    func testRun() {
        var logic = CitizenLogic()
        logic.run()
    }
}
""".strip()
        + "\n",
    )
