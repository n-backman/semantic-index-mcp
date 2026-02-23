from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .schemas import CACHE_FILENAME, GRAPH_DIRNAME, GRAPH_FILENAME
from .schemas import STATE_DIR_ENV, STATE_KEY_ENV


def _repo_state_key(repo_root: Path) -> str:
    resolved = repo_root.resolve()
    slug = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in resolved.name
    ).strip("-")
    if not slug:
        slug = "repo"
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    return f"{slug}-{digest}"


def semantic_index_dir(repo_root: Path) -> Path:
    configured = os.environ.get(STATE_DIR_ENV, "").strip()
    if configured:
        key = os.environ.get(STATE_KEY_ENV, "").strip() or _repo_state_key(repo_root)
        return Path(configured).expanduser().resolve() / key
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
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp_path).replace(path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


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
    result = read_json(path)
    if result is None:
        return {"files": {}}
    return result


def save_cache(repo_root: Path, payload: dict[str, Any]) -> Path:
    path = cache_path(repo_root)
    write_json(path, payload)
    return path
