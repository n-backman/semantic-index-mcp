#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__ is None or __package__ == "":
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from semantic_index.graph_store import graph_path
    from semantic_index.indexer import ParseError, SemanticIndexer, doctor_check
    from semantic_index.mcp_server import serve
else:
    from .graph_store import graph_path
    from .indexer import ParseError, SemanticIndexer, doctor_check
    from .mcp_server import serve


def cmd_build(repo_root: Path) -> int:
    indexer = SemanticIndexer(repo_root)
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


def cmd_refresh(repo_root: Path) -> int:
    indexer = SemanticIndexer(repo_root)
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
    ok, messages = doctor_check(repo_root, strict=strict)
    payload = {
        "ok": ok,
        "strict": strict,
        "messages": messages,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if ok else 1


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

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="Full rebuild of graph and cache.")
    sub.add_parser("refresh", help="Incremental refresh using file-hash cache.")

    doctor_parser = sub.add_parser("doctor", help="Validate index schema and references.")
    doctor_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when graph file is missing.",
    )

    sub.add_parser("serve-mcp", help="Run MCP stdio server backed by graph.json.")

    args = parser.parse_args()
    repo_root = args.repo_root.resolve()

    try:
        if args.command == "build":
            return cmd_build(repo_root)
        if args.command == "refresh":
            return cmd_refresh(repo_root)
        if args.command == "doctor":
            return cmd_doctor(repo_root, strict=bool(args.strict))
        if args.command == "serve-mcp":
            return serve(repo_root)
        parser.error(f"unknown command: {args.command}")
        return 2
    except ParseError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
