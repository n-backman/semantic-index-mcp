from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..plugin_api import LanguagePlugin, ParsedFile

_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
    re.MULTILINE,
)
_ARROW_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s+)?\(",
    re.MULTILINE,
)
_CLASS_RE = re.compile(
    r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)
_IMPORT_RE = re.compile(
    r"""^\s*import\s+(?:[^'"]*from\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def _line_number(source: str, match_start: int) -> int:
    return source[:match_start].count("\n") + 1


class TypeScriptPlugin(LanguagePlugin):
    language = "typescript"
    extensions = frozenset({".ts", ".tsx"})

    def parse_file(self, path: Path) -> ParsedFile:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ParsedFile(symbols=[], edges=[])

        file_path = str(path)
        symbols: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        for m in _CLASS_RE.finditer(source):
            line = _line_number(source, m.start())
            name = m.group(1)
            symbols.append({
                "id": f"{file_path}::{name}:{line}",
                "name": name,
                "kind": "type",
                "file": file_path,
                "line": line,
            })

        for m in _FUNC_RE.finditer(source):
            line = _line_number(source, m.start())
            name = m.group(1)
            symbols.append({
                "id": f"{file_path}::{name}:{line}",
                "name": name,
                "kind": "function",
                "file": file_path,
                "line": line,
            })

        for m in _ARROW_RE.finditer(source):
            line = _line_number(source, m.start())
            name = m.group(1)
            symbols.append({
                "id": f"{file_path}::{name}:{line}",
                "name": name,
                "kind": "function",
                "file": file_path,
                "line": line,
            })

        for m in _IMPORT_RE.finditer(source):
            line = _line_number(source, m.start())
            edges.append({
                "kind": "import",
                "src_file": file_path,
                "dst_module": m.group(1),
                "line": line,
            })

        return ParsedFile(symbols=symbols, edges=edges)

    def classify_file(self, rel_path: str, parsed: ParsedFile) -> str | None:
        lower = rel_path.replace("\\", "/").lower()
        if "test" in lower or "spec" in lower or ".test." in lower or ".spec." in lower:
            return "Auditor"
        if any(s in lower for s in ("/config", "/settings", "/constants")):
            return "Law"
        return None
