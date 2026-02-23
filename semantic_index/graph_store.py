from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import CACHE_FILENAME, GRAPH_DIRNAME, GRAPH_FILENAME


def semantic_index_dir(repo_root: Path) -> Path:
    return repo_root / GRAPH_DIRNAME


def graph_path(repo_root: Path) -> Path:
    return semantic_index_dir(repo_root) / GRAPH_FILENAME


def cache_path(repo_root: Path) -> Path:
    return semantic_index_dir(repo_root) / CACHE_FILENAME


def _sorted_unique(values: list[str]) -> list[str]:
    return sorted(set(values))


def normalize_graph(graph: dict[str, Any]) -> dict[str, Any]:
    graph = dict(graph)

    graph["files"] = sorted(graph.get("files", []), key=lambda item: item.get("path", ""))
    graph["symbols"] = sorted(graph.get("symbols", []), key=lambda item: item.get("id", ""))

    graph["edges_calls"] = sorted(
        graph.get("edges_calls", []),
        key=lambda item: (
            item.get("source", ""),
            item.get("resolution", ""),
            item.get("target") or "",
            item.get("target_name", ""),
            int(item.get("line", 0)),
        ),
    )
    graph["edges_mutations"] = sorted(
        graph.get("edges_mutations", []),
        key=lambda item: (
            item.get("source", ""),
            item.get("target_symbol") or "",
            item.get("target_name", ""),
            int(item.get("line", 0)),
        ),
    )
    graph["edges_depends_on"] = sorted(
        graph.get("edges_depends_on", []),
        key=lambda item: (item.get("source_file", ""), item.get("target_file", "")),
    )

    impact = graph.get("impact", {})
    symbol_impact = impact.get("symbols", {})
    file_impact = impact.get("files", {})
    graph["impact"] = {
        "symbols": {key: symbol_impact[key] for key in sorted(symbol_impact)},
        "files": {key: file_impact[key] for key in sorted(file_impact)},
    }

    indexes = graph.get("indexes", {})
    normalized_indexes: dict[str, Any] = {}
    for key in sorted(indexes):
        value = indexes[key]
        if isinstance(value, dict):
            normalized_indexes[key] = {
                sub_key: (
                    _sorted_unique(sub_value)
                    if isinstance(sub_value, list)
                    else sub_value
                )
                for sub_key, sub_value in sorted(value.items())
            }
        else:
            normalized_indexes[key] = value
    graph["indexes"] = normalized_indexes

    return graph


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_graph(repo_root: Path) -> dict[str, Any] | None:
    path = graph_path(repo_root)
    if not path.exists():
        return None
    return read_json(path)


def save_graph(repo_root: Path, graph: dict[str, Any]) -> Path:
    normalized = normalize_graph(graph)
    path = graph_path(repo_root)
    write_json(path, normalized)
    return path


def load_cache(repo_root: Path) -> dict[str, Any]:
    path = cache_path(repo_root)
    if not path.exists():
        return {"files": {}}
    return read_json(path)


def save_cache(repo_root: Path, payload: dict[str, Any]) -> Path:
    path = cache_path(repo_root)
    write_json(path, payload)
    return path
