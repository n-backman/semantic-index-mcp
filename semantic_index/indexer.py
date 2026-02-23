from __future__ import annotations

import hashlib
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ast_parser import ParseError, file_sha256
from .extract_atoms import (
    build_file_records,
    build_symbol_indexes,
    flatten_calls,
    flatten_mutations,
    flatten_symbols,
)
from .graph_store import load_cache, load_graph, save_cache, save_graph
from .impact import build_dependency_edges, compute_impact
from .plugin_api import ParsedFile
from .plugin_registry import PluginRegistry
from .resolve_calls import resolve_calls
from .schemas import (
    CACHE_VERSION,
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


def normalize_roots(repo_root: Path, roots: list[Path] | None = None) -> list[Path]:
    ordered = [repo_root.resolve()]
    if roots:
        ordered.extend(path.resolve() for path in roots)

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in ordered:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _workspace_rel_path(root: Path, rel_path: str) -> str:
    return f"{root.name}/{rel_path}"


def _resolve_indexable_path(root: Path, rel_path: str) -> Path | None:
    candidate = root / rel_path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        return None
    return resolved


def _discover_files_for_root(
    root: Path, extensions: frozenset[str]
) -> list[tuple[str, Path]]:
    code, output = _run_git(root, "ls-files")
    rel_paths: list[str]
    if code == 0 and output:
        rel_paths = [
            line for line in output.splitlines()
            if any(line.endswith(ext) for ext in extensions)
        ]
    else:
        rel_paths = []
        for ext in extensions:
            for path in root.rglob(f"*{ext}"):
                if ".git" not in path.parts and ".build" not in path.parts:
                    rel_paths.append(path.relative_to(root).as_posix())

    rel_paths = sorted(set(rel_paths))
    files: list[tuple[str, Path]] = []
    for rel_path in rel_paths:
        resolved = _resolve_indexable_path(root, rel_path)
        if resolved is None:
            continue
        files.append((rel_path, resolved))
    return files


def _discover_swift_files_for_root(root: Path) -> list[tuple[str, Path]]:
    return _discover_files_for_root(root, frozenset({".swift"}))


def discover_files(
    repo_root: Path,
    roots: list[Path] | None = None,
    registry: PluginRegistry | None = None,
) -> list[tuple[str, Path]]:
    extensions = registry.all_extensions() if registry else frozenset({".swift"})
    files: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for root in normalize_roots(repo_root, roots):
        for rel_path, abs_path in _discover_files_for_root(root, extensions):
            if abs_path in seen:
                continue
            seen.add(abs_path)
            files.append((_workspace_rel_path(root, rel_path), abs_path))

    files.sort(key=lambda item: item[0])
    return files


def discover_swift_files(
    repo_root: Path, roots: list[Path] | None = None
) -> list[tuple[str, Path]]:
    """Backward-compatible wrapper; discovers only .swift files."""
    files: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for root in normalize_roots(repo_root, roots):
        for rel_path, abs_path in _discover_swift_files_for_root(root):
            if abs_path in seen:
                continue
            seen.add(abs_path)
            files.append((_workspace_rel_path(root, rel_path), abs_path))

    files.sort(key=lambda item: item[0])
    return files


def _root_digest(root: Path) -> str:
    code, head = _run_git(root, "rev-parse", "HEAD")
    if code != 0 or not head:
        return f"{root.name}:no-git"
    code, dirty = _run_git(root, "status", "--porcelain")
    if code == 0 and dirty:
        digest = hashlib.sha256(dirty.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"{root.name}:{head}-dirty-{digest}"
    return f"{root.name}:{head}"


def repo_digest(repo_root: Path, roots: list[Path] | None = None) -> str:
    root_digests = [_root_digest(root) for root in normalize_roots(repo_root, roots)]
    if len(root_digests) == 1:
        return root_digests[0].split(":", 1)[1]
    joined = "\n".join(root_digests)
    digest = hashlib.sha256(joined.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"workspace-{digest}"


def _parsed_to_analysis(
    rel_path: str, abs_path: Path, file_hash: str, parsed: ParsedFile
) -> dict[str, Any]:
    """Convert a ParsedFile to the internal analysis dict format."""
    file_path = str(abs_path)
    for sym in parsed.symbols:
        sym.setdefault("file", file_path)

    calls = [
        {k: v for k, v in e.items() if k != "kind"}
        for e in parsed.edges
        if e.get("kind") == "call"
    ]
    mutations = [
        {k: v for k, v in e.items() if k != "kind"}
        for e in parsed.edges
        if e.get("kind") == "mutation"
    ]

    return {
        "file": file_path,
        "hash": file_hash,
        "rel_path": rel_path,
        "types": [s for s in parsed.symbols if s.get("kind") == "type"],
        "functions": [s for s in parsed.symbols if s.get("kind") == "function"],
        "variables": [s for s in parsed.symbols if s.get("kind") == "variable"],
        "calls": calls,
        "mutations": mutations,
    }


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

    files_by_role: dict[str, list[str]] = defaultdict(list)
    for file_record in files:
        role = file_record.get("role")
        if role:
            files_by_role[role].append(file_record["id"])

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
            "files_by_role": {
                key: sorted(value) for key, value in sorted(files_by_role.items())
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
    def __init__(
        self,
        repo_root: Path,
        roots: list[Path] | None = None,
        registry: PluginRegistry | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.roots = normalize_roots(self.repo_root, roots)
        self.registry = registry if registry is not None else PluginRegistry()

    def build(self, incremental: bool = True) -> tuple[dict[str, Any], BuildStats]:
        started = time.perf_counter()
        existing_graph = load_graph(self.repo_root)

        files = discover_files(self.repo_root, self.roots[1:], self.registry)
        cache = load_cache(self.repo_root) if incremental else {"files": {}}
        cache_files = cache.get("files", {}) if isinstance(cache, dict) else {}
        valid_cache = (
            isinstance(cache, dict)
            and cache.get("cache_version") == CACHE_VERSION
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
            ext = abs_path.suffix.lower()
            plugin = self.registry.get(ext)
            cached_entry = cache_files.get(str(abs_path)) if incremental else None

            parsed = None
            if (
                cached_entry
                and cached_entry.get("hash") == digest
                and isinstance(cached_entry.get("parsed"), dict)
            ):
                try:
                    parsed = ParsedFile.from_dict(cached_entry["parsed"])
                    files_reused += 1
                except Exception:
                    parsed = None

            if parsed is None:
                if plugin is None:
                    # No plugin for this extension — skip
                    continue
                parsed = plugin.parse_file(abs_path)
                files_reparsed += 1

            analysis = _parsed_to_analysis(rel_path, abs_path, digest, parsed)
            analyses.append(analysis)
            file_hash_pairs.append((rel_path, digest))
            new_cache_files[str(abs_path)] = {
                "hash": digest,
                "parsed": parsed.to_dict(),
            }

        analyses.sort(key=lambda item: item["rel_path"])

        role_by_file: dict[str, str | None] = {}
        for analysis in analyses:
            abs_path = Path(analysis["file"])
            ext = abs_path.suffix.lower()
            plugin = self.registry.get(ext)
            rel_path = analysis["rel_path"]
            # Reconstruct ParsedFile for classify_file (symbols already split)
            parsed_for_classify = ParsedFile(
                symbols=(
                    analysis.get("types", [])
                    + analysis.get("functions", [])
                    + analysis.get("variables", [])
                ),
                edges=[],
            )
            role = plugin.classify_file(rel_path, parsed_for_classify) if plugin else None
            role_by_file[analysis["file"]] = role

        symbols = flatten_symbols(analyses)
        for symbol in symbols:
            symbol["role"] = role_by_file.get(symbol["file"])
            symbol["is_public_api"] = symbol.get("visibility") in {"public", "open"}

        calls = flatten_calls(analyses)
        mutations = flatten_mutations(analyses)

        edges_calls = resolve_calls(symbols, calls)
        edges_mutations = _resolve_mutation_edges(symbols, mutations)

        symbols_by_id = {symbol["id"]: symbol for symbol in symbols}
        edges_depends_on = build_dependency_edges(symbols_by_id, edges_calls)

        files_payload = build_file_records(analyses, role_by_file)
        indexes = _build_indexes(symbols, files_payload, edges_calls)

        def _score_fn(symbol: dict[str, Any], base_score: float) -> float:
            file_path = symbol.get("file", "")
            ext = Path(file_path).suffix.lower()
            p = self.registry.get(ext)
            return p.score_symbol(symbol, base_score) if p else base_score

        impact = compute_impact(symbols, edges_calls, edges_mutations, _score_fn)

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
                "generated_at": generated_at,
                "repo_root": str(self.repo_root),
                "workspace_roots": [str(root) for root in self.roots],
                "repo_digest": repo_digest(self.repo_root, self.roots[1:]),
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
    "discover_files",
    "discover_swift_files",
    "normalize_roots",
    "repo_digest",
    "ParseError",
]
