from __future__ import annotations

import hashlib
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ast_parser import ParseError, analyze_file, file_sha256
from .classify_culture import classify_file
from .extract_atoms import (
    build_file_records,
    build_symbol_indexes,
    flatten_calls,
    flatten_mutations,
    flatten_symbols,
)
from .graph_store import load_cache, load_graph, save_cache, save_graph
from .impact import build_dependency_edges, compute_impact
from .resolve_calls import resolve_calls
from .schemas import (
    CACHE_VERSION,
    PARSER_VERSION,
    SCHEMA_VERSION,
    BuildStats,
    EDGE_RESOLUTION_AMBIGUOUS,
    EDGE_RESOLUTION_EXTERNAL,
    EDGE_RESOLUTION_RESOLVED,
)


def _run_git(repo_root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout.strip()


def discover_swift_files(repo_root: Path) -> list[tuple[str, Path]]:
    code, output = _run_git(repo_root, "ls-files")
    rel_paths: list[str]
    if code == 0 and output:
        rel_paths = [line for line in output.splitlines() if line.endswith(".swift")]
    else:
        rel_paths = [
            path.relative_to(repo_root).as_posix()
            for path in repo_root.rglob("*.swift")
            if ".git" not in path.parts and ".build" not in path.parts
        ]

    rel_paths = sorted(set(rel_paths))
    return [(rel, (repo_root / rel).resolve()) for rel in rel_paths]


def repo_digest(repo_root: Path) -> str:
    code, head = _run_git(repo_root, "rev-parse", "HEAD")
    if code != 0 or not head:
        return "no-git"
    code, dirty = _run_git(repo_root, "status", "--porcelain")
    if code == 0 and dirty:
        digest = hashlib.sha256(dirty.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"{head}-dirty-{digest}"
    return head


def _resolve_mutation_edges(
    symbols: list[dict[str, Any]],
    mutations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    symbols_by_id = {symbol["id"]: symbol for symbol in symbols}

    variable_index_file_name: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    variable_index_file_container_name: dict[tuple[str, str, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for symbol in symbols:
        if symbol.get("kind") != "variable":
            continue
        file_path = symbol["file"]
        name = symbol["name"]
        container = symbol.get("container", "global")
        variable_index_file_name[(file_path, name)].append(symbol)
        variable_index_file_container_name[(file_path, container, name)].append(symbol)

    edges: list[dict[str, Any]] = []

    for event in mutations:
        source = event.get("source_symbol_id")
        source_symbol = symbols_by_id.get(source)
        if not source_symbol:
            continue

        source_file = source_symbol["file"]
        source_container = source_symbol.get("container", "global")
        target_name = event.get("target_name")
        candidates = variable_index_file_container_name.get(
            (source_file, source_container, target_name),
            [],
        )
        if not candidates:
            candidates = variable_index_file_name.get((source_file, target_name), [])

        if len(candidates) == 1:
            target_symbol = candidates[0]
            edges.append(
                {
                    "source": source,
                    "target_symbol": target_symbol["id"],
                    "target_name": target_name,
                    "target_candidates": [target_symbol["id"]],
                    "target_kind": event.get("target_kind", "unknown"),
                    "resolution": EDGE_RESOLUTION_RESOLVED,
                    "confidence": 1.0,
                    "line": int(event.get("line", 0)),
                }
            )
        elif len(candidates) > 1:
            ids = sorted(candidate["id"] for candidate in candidates)
            edges.append(
                {
                    "source": source,
                    "target_symbol": None,
                    "target_name": target_name,
                    "target_candidates": ids,
                    "target_kind": event.get("target_kind", "unknown"),
                    "resolution": EDGE_RESOLUTION_AMBIGUOUS,
                    "confidence": max(0.1, round(1.0 / len(ids), 4)),
                    "line": int(event.get("line", 0)),
                }
            )
        else:
            edges.append(
                {
                    "source": source,
                    "target_symbol": None,
                    "target_name": target_name,
                    "target_candidates": [],
                    "target_kind": event.get("target_kind", "unknown"),
                    "resolution": EDGE_RESOLUTION_EXTERNAL,
                    "confidence": float(event.get("confidence", 0.8)),
                    "line": int(event.get("line", 0)),
                }
            )

    edges.sort(
        key=lambda item: (
            item["source"],
            item["resolution"],
            item.get("target_symbol") or "",
            item["target_name"],
            item["line"],
        )
    )
    return edges


def _build_indexes(
    symbols: list[dict[str, Any]],
    files: list[dict[str, Any]],
    edges_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    indexes = build_symbol_indexes(symbols)

    files_by_culture: dict[str, list[str]] = defaultdict(list)
    for file_record in files:
        files_by_culture[file_record["culture"]].append(file_record["id"])

    callers_by_symbol: dict[str, set[str]] = defaultdict(set)
    callees_by_symbol: dict[str, set[str]] = defaultdict(set)
    unresolved_calls_by_symbol: dict[str, list[str]] = defaultdict(list)

    for edge in edges_calls:
        source = edge.get("source")
        resolution = edge.get("resolution")
        target = edge.get("target")
        target_name = edge.get("target_name", "")

        if resolution == EDGE_RESOLUTION_RESOLVED and source and target:
            callers_by_symbol[target].add(source)
            callees_by_symbol[source].add(target)
        elif source:
            unresolved_calls_by_symbol[source].append(target_name)

    indexes.update(
        {
            "files_by_culture": {
                key: sorted(value) for key, value in sorted(files_by_culture.items())
            },
            "callers_by_symbol": {
                key: sorted(value) for key, value in sorted(callers_by_symbol.items())
            },
            "callees_by_symbol": {
                key: sorted(value) for key, value in sorted(callees_by_symbol.items())
            },
            "unresolved_calls_by_symbol": {
                key: sorted(value)
                for key, value in sorted(unresolved_calls_by_symbol.items())
            },
        }
    )

    return indexes


class SemanticIndexer:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()

    def build(self, incremental: bool = True) -> tuple[dict[str, Any], BuildStats]:
        started = time.perf_counter()
        existing_graph = load_graph(self.repo_root)

        files = discover_swift_files(self.repo_root)
        cache = load_cache(self.repo_root) if incremental else {"files": {}}
        cache_files = cache.get("files", {}) if isinstance(cache, dict) else {}
        valid_cache = (
            isinstance(cache, dict)
            and cache.get("cache_version") == CACHE_VERSION
            and cache.get("parser_version") == PARSER_VERSION
            and isinstance(cache_files, dict)
        )
        if not valid_cache:
            cache_files = {}

        analyses: list[dict[str, Any]] = []
        file_hash_pairs: list[tuple[str, str]] = []
        files_reparsed = 0
        files_reused = 0
        new_cache_files: dict[str, Any] = {}

        for rel_path, abs_path in files:
            digest = file_sha256(abs_path)
            cached_entry = cache_files.get(str(abs_path)) if incremental else None
            if (
                cached_entry
                and cached_entry.get("hash") == digest
                and isinstance(cached_entry.get("analysis"), dict)
            ):
                analysis = dict(cached_entry["analysis"])
                analysis["hash"] = digest
                analysis["file"] = str(abs_path)
                analysis["rel_path"] = rel_path
                files_reused += 1
            else:
                analysis = analyze_file(abs_path)
                analysis["rel_path"] = rel_path
                files_reparsed += 1

            analyses.append(analysis)
            file_hash_pairs.append((rel_path, digest))
            new_cache_files[str(abs_path)] = {
                "hash": digest,
                "analysis": analysis,
            }

        analyses.sort(key=lambda item: item["rel_path"])

        culture_by_file: dict[str, str] = {}
        for analysis in analyses:
            culture = classify_file(analysis["rel_path"], analysis)
            culture_by_file[analysis["file"]] = culture

        symbols = flatten_symbols(analyses)
        for symbol in symbols:
            symbol["culture"] = culture_by_file.get(symbol["file"], "Citizen")
            symbol["is_public_api"] = symbol.get("visibility") in {"public", "open"}

        calls = flatten_calls(analyses)
        mutations = flatten_mutations(analyses)

        edges_calls = resolve_calls(symbols, calls)
        edges_mutations = _resolve_mutation_edges(symbols, mutations)

        symbols_by_id = {symbol["id"]: symbol for symbol in symbols}
        edges_depends_on = build_dependency_edges(symbols_by_id, edges_calls)

        files_payload = build_file_records(analyses, culture_by_file)
        indexes = _build_indexes(symbols, files_payload, edges_calls)
        impact = compute_impact(symbols, edges_calls, edges_mutations, culture_by_file)

        duration_ms = int((time.perf_counter() - started) * 1000)
        content_digest_input = "\n".join(
            f"{rel}:{digest}" for rel, digest in sorted(file_hash_pairs)
        )
        content_digest = hashlib.sha256(
            content_digest_input.encode("utf-8", errors="ignore")
        ).hexdigest()

        generated_at = datetime.now(timezone.utc).isoformat()
        persisted_duration = duration_ms
        persisted_reparsed = files_reparsed
        persisted_reused = files_reused
        if existing_graph and isinstance(existing_graph, dict):
            existing_meta = existing_graph.get("meta", {})
            if existing_meta.get("content_digest") == content_digest:
                generated_at = existing_meta.get("generated_at", generated_at)
                persisted_duration = int(existing_meta.get("build_duration_ms", duration_ms))
                persisted_reparsed = int(existing_meta.get("files_reparsed", files_reparsed))
                persisted_reused = int(existing_meta.get("files_reused", files_reused))

        graph = {
            "meta": {
                "schema_version": SCHEMA_VERSION,
                "parser_version": PARSER_VERSION,
                "generated_at": generated_at,
                "repo_root": str(self.repo_root),
                "repo_digest": repo_digest(self.repo_root),
                "content_digest": content_digest,
                "build_duration_ms": persisted_duration,
                "files_total": len(files),
                "files_reparsed": persisted_reparsed,
                "files_reused": persisted_reused,
            },
            "files": files_payload,
            "symbols": symbols,
            "edges_calls": edges_calls,
            "edges_mutations": edges_mutations,
            "edges_depends_on": edges_depends_on,
            "impact": impact,
            "indexes": indexes,
        }

        save_graph(self.repo_root, graph)
        save_cache(
            self.repo_root,
            {
                "cache_version": CACHE_VERSION,
                "parser_version": PARSER_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "files": new_cache_files,
            },
        )

        stats = BuildStats(
            files_total=len(files),
            files_reparsed=files_reparsed,
            files_reused=files_reused,
            symbols_total=len(symbols),
            call_edges_total=len(edges_calls),
            mutation_edges_total=len(edges_mutations),
            duration_ms=duration_ms,
        )
        return graph, stats

    def build_full(self) -> tuple[dict[str, Any], BuildStats]:
        return self.build(incremental=False)

    def build_incremental(self) -> tuple[dict[str, Any], BuildStats]:
        return self.build(incremental=True)


def doctor_check(repo_root: Path, strict: bool = False) -> tuple[bool, list[str]]:
    from .graph_store import graph_path, load_graph
    from .schemas import validate_graph_shape

    graph_file = graph_path(repo_root)
    if not graph_file.exists():
        if strict:
            return False, [f"graph file missing: {graph_file}"]
        return True, [f"graph file missing: {graph_file} (skipped)"]

    graph = load_graph(repo_root)
    if graph is None:
        return False, ["failed to load graph json"]

    errors = validate_graph_shape(graph)

    symbol_ids = {item["id"] for item in graph.get("symbols", []) if "id" in item}
    file_ids = {item["id"] for item in graph.get("files", []) if "id" in item}

    for edge in graph.get("edges_calls", []):
        source = edge.get("source")
        target = edge.get("target")
        if source and source not in symbol_ids:
            errors.append(f"call edge source missing symbol: {source}")
        if target and target not in symbol_ids:
            errors.append(f"call edge target missing symbol: {target}")

    for edge in graph.get("edges_depends_on", []):
        if edge.get("source_file") not in file_ids:
            errors.append(f"dependency edge source file missing: {edge.get('source_file')}")
        if edge.get("target_file") not in file_ids:
            errors.append(f"dependency edge target file missing: {edge.get('target_file')}")

    indexes = graph.get("indexes", {})
    for sid_list in indexes.get("symbols_by_file", {}).values():
        for sid in sid_list:
            if sid not in symbol_ids:
                errors.append(f"index references missing symbol: {sid}")

    return len(errors) == 0, errors


__all__ = [
    "SemanticIndexer",
    "doctor_check",
    "discover_swift_files",
    "repo_digest",
    "ParseError",
]
