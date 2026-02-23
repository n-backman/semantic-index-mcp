from __future__ import annotations

from pathlib import Path
from typing import Any

from ..plugin_api import LanguagePlugin, ParsedFile


class SwiftPlugin(LanguagePlugin):
    language = "swift"
    extensions = frozenset({".swift"})

    def parse_file(self, path: Path) -> ParsedFile:
        from ..ast_parser import analyze_file

        analysis = analyze_file(path)
        symbols: list[dict[str, Any]] = []
        symbols.extend(analysis.get("types", []))
        symbols.extend(analysis.get("functions", []))
        symbols.extend(analysis.get("variables", []))

        edges: list[dict[str, Any]] = []
        for call in analysis.get("calls", []):
            edges.append({**call, "kind": "call"})
        for mut in analysis.get("mutations", []):
            edges.append({**mut, "kind": "mutation"})

        return ParsedFile(symbols=symbols, edges=edges)

    def classify_file(self, rel_path: str, parsed: ParsedFile) -> str | None:
        from ..classify_culture import classify_file as _classify_culture

        types = [s for s in parsed.symbols if s.get("kind") == "type"]
        functions = [s for s in parsed.symbols if s.get("kind") == "function"]
        analysis_like: dict[str, Any] = {"types": types, "functions": functions}
        return _classify_culture(rel_path, analysis_like)

    def score_symbol(self, symbol: dict, base_score: float) -> float:
        from ..classify_culture import culture_multiplier

        role = symbol.get("role") or "Citizen"
        return round(base_score * culture_multiplier(role), 4)
