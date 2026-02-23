from __future__ import annotations

from collections import defaultdict
from typing import Any


def flatten_symbols(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for analysis in analyses:
        symbols.extend(analysis.get("types", []))
        symbols.extend(analysis.get("functions", []))
        symbols.extend(analysis.get("variables", []))
    symbols.sort(key=lambda item: item["id"])
    return symbols


def flatten_calls(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for analysis in analyses:
        calls.extend(analysis.get("calls", []))
    calls.sort(
        key=lambda item: (
            item.get("source_symbol_id", ""),
            item.get("callee_name", ""),
            int(item.get("line", 0)),
        )
    )
    return calls


def flatten_mutations(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mutations: list[dict[str, Any]] = []
    for analysis in analyses:
        mutations.extend(analysis.get("mutations", []))
    mutations.sort(
        key=lambda item: (
            item.get("source_symbol_id", ""),
            item.get("target_name", ""),
            int(item.get("line", 0)),
        )
    )
    return mutations


def build_file_records(
    analyses: list[dict[str, Any]],
    culture_by_file: dict[str, str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for analysis in analyses:
        file_path = analysis["file"]
        culture = culture_by_file[file_path]
        records.append(
            {
                "id": file_path,
                "path": analysis.get("rel_path", file_path),
                "hash": analysis.get("hash"),
                "culture": culture,
                "atom_counts": {
                    "types": len(analysis.get("types", [])),
                    "functions": len(analysis.get("functions", [])),
                    "variables": len(analysis.get("variables", [])),
                },
                "mutation_count": len(analysis.get("mutations", [])),
            }
        )

    records.sort(key=lambda item: item["path"])
    return records


def build_symbol_indexes(symbols: list[dict[str, Any]]) -> dict[str, Any]:
    symbols_by_name: dict[str, list[str]] = defaultdict(list)
    symbols_by_file: dict[str, list[str]] = defaultdict(list)

    for symbol in symbols:
        sid = symbol["id"]
        name_key = symbol.get("name", "").lower()
        symbols_by_name[name_key].append(sid)
        symbols_by_file[symbol["file"]].append(sid)

    return {
        "symbols_by_name": {
            key: sorted(value) for key, value in sorted(symbols_by_name.items())
        },
        "symbols_by_file": {
            key: sorted(value) for key, value in sorted(symbols_by_file.items())
        },
    }
