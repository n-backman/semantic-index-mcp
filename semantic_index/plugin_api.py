from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedFile:
    symbols: list[dict]  # {id, name, kind, file, line, [visibility, signature, container, arity, ...]}
    edges: list[dict]    # {kind: "call"|"mutation"|"import", ...per-kind fields}

    def to_dict(self) -> dict:
        return {"symbols": self.symbols, "edges": self.edges}

    @classmethod
    def from_dict(cls, data: dict) -> "ParsedFile":
        return cls(symbols=data.get("symbols", []), edges=data.get("edges", []))


class LanguagePlugin:
    language: str = ""
    extensions: frozenset[str] = frozenset()

    def parse_file(self, path: Path) -> ParsedFile:
        """REQUIRED. Extract symbols and edges from a single file."""
        raise NotImplementedError

    def classify_file(self, rel_path: str, parsed: ParsedFile) -> str | None:
        """OPTIONAL. Return a role label (e.g. 'View', 'Service') or None."""
        return None

    def score_symbol(self, symbol: dict, base_score: float) -> float:
        """OPTIONAL. Adjust impact score for a symbol. Default: pass-through."""
        return base_score
