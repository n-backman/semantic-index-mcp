#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

if __package__ is None or __package__ == "":
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from semantic_index.auto_index import AutoIndexManager
    from semantic_index.graph_store import graph_path
    from semantic_index.indexer import ParseError, SemanticIndexer, doctor_check
    from semantic_index.mcp_server import serve
else:
    from .auto_index import AutoIndexManager
    from .graph_store import graph_path
    from .indexer import ParseError, SemanticIndexer, doctor_check
    from .mcp_server import serve


def cmd_build(repo_root: Path, roots: list[Path] | None = None) -> int:
    indexer = SemanticIndexer(repo_root, roots)
    _, stats = indexer.build_full()
    output = {
        "mode": "build",
        "graph": str(graph_path(repo_root)),
        "files_total": stats.files_total,
        "files_reparsed": stats.files_reparsed,
        "files_reused": stats.files_reused,
        "symbols_total": stats.symbols_total,
        "call_edges_total": stats.call_edges_total,
        "mutation_edges_total": stats.mutation_edges_total,
        "duration_ms": stats.duration_ms,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def cmd_refresh(repo_root: Path, roots: list[Path] | None = None) -> int:
    indexer = SemanticIndexer(repo_root, roots)
    _, stats = indexer.build_incremental()
    output = {
        "mode": "refresh",
        "graph": str(graph_path(repo_root)),
        "files_total": stats.files_total,
        "files_reparsed": stats.files_reparsed,
        "files_reused": stats.files_reused,
        "symbols_total": stats.symbols_total,
        "call_edges_total": stats.call_edges_total,
        "mutation_edges_total": stats.mutation_edges_total,
        "duration_ms": stats.duration_ms,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def cmd_doctor(repo_root: Path, strict: bool) -> int:
    from .plugin_registry import PluginRegistry

    registry = PluginRegistry()
    plugins_info = [
        {
            "language": p.language,
            "extensions": sorted(p.extensions),
        }
        for p in registry.all_plugins()
    ]

    ok, messages = doctor_check(repo_root, strict=strict)
    payload = {
        "ok": ok,
        "strict": strict,
        "plugins": plugins_info,
        "messages": messages,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if ok else 1


def cmd_watch(
    repo_root: Path,
    roots: list[Path] | None = None,
    bootstrap_index: bool = False,
    watch_interval: float = 2.0,
) -> int:
    def _log(message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        print(f"[{timestamp}] {message}", flush=True)

    manager = AutoIndexManager(
        repo_root=repo_root,
        roots=roots,
        watch=True,
        watch_interval=watch_interval,
        on_refresh=lambda stats: _log(
            "refreshed graph "
            f"files_total={stats.files_total} "
            f"files_reparsed={stats.files_reparsed} "
            f"files_reused={stats.files_reused} "
            f"duration_ms={stats.duration_ms}"
        ),
        on_error=lambda error: _log(f"watcher error: {error}"),
    )

    def _shutdown(_signum: int, _frame: object) -> None:
        manager.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    _log(
        "starting watcher "
        f"repo_root={repo_root} roots={[str(path) for path in roots or []]} "
        f"bootstrap_index={bootstrap_index} watch_interval={watch_interval}"
    )
    manager.start(bootstrap=bootstrap_index)
    try:
        manager.wait_forever()
    finally:
        manager.stop()
    return 0


def configure_state_dir(state_dir: Path | None) -> None:
    if state_dir is None:
        return
    os.environ["SEMANTIC_INDEX_STATE_DIR"] = str(state_dir.expanduser().resolve())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AST-first semantic index and MCP server for this Swift repository."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: current working directory).",
    )
    parser.add_argument(
        "--root",
        dest="roots",
        type=Path,
        action="append",
        help="Additional sibling root to include in the indexed workspace. Repeatable.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        help="Optional persistent state root for graph/cache files.",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="Full rebuild of graph and cache.")
    sub.add_parser("refresh", help="Incremental refresh using file-hash cache.")

    doctor_parser = sub.add_parser("doctor", help="Validate index schema and references.")
    doctor_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when graph file is missing.",
    )

    serve_parser = sub.add_parser("serve-mcp", help="Run MCP stdio server backed by graph.json.")
    serve_parser.add_argument(
        "--bootstrap-index",
        action="store_true",
        help="Build or refresh the graph before serving requests.",
    )
    serve_parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch the repository for Swift file changes and refresh incrementally.",
    )
    serve_parser.add_argument(
        "--watch-interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds for watch mode (default: 2.0).",
    )

    watch_parser = sub.add_parser("watch", help="Run a persistent background index watcher.")
    watch_parser.add_argument(
        "--bootstrap-index",
        action="store_true",
        help="Build or refresh the graph before starting the watcher.",
    )
    watch_parser.add_argument(
        "--watch-interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds for watch mode (default: 2.0).",
    )

    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    roots = [path.resolve() for path in (args.roots or [])]
    configure_state_dir(args.state_dir)

    try:
        if args.command == "build":
            return cmd_build(repo_root, roots)
        if args.command == "refresh":
            return cmd_refresh(repo_root, roots)
        if args.command == "doctor":
            return cmd_doctor(repo_root, strict=bool(args.strict))
        if args.command == "serve-mcp":
            return serve(
                repo_root,
                roots=roots,
                bootstrap_index=bool(args.bootstrap_index),
                watch=bool(args.watch),
                watch_interval=float(args.watch_interval),
            )
        if args.command == "watch":
            return cmd_watch(
                repo_root,
                roots,
                bootstrap_index=bool(args.bootstrap_index),
                watch_interval=float(args.watch_interval),
            )
        parser.error(f"unknown command: {args.command}")
        return 2
    except ParseError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
