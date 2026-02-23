# Semantic Index MCP

AST-first semantic index + MCP guardrail server for Swift codebases.

This project parses Swift source via `swiftc -typecheck -dump-parse`, builds a deterministic graph JSON, and serves metadata-only MCP tools.

## CLI

Use the standalone CLI:

```bash
python3 semantic_index/cli.py --repo-root /path/to/your/repo build
python3 semantic_index/cli.py --repo-root /path/to/your/repo refresh
python3 semantic_index/cli.py --repo-root /path/to/your/repo doctor --strict
python3 semantic_index/cli.py --repo-root /path/to/your/repo serve-mcp
```

## Graph Outputs

For any target repo, artifacts are written into that repo:

- `<repo>/.semantic-index/graph.json`
- `<repo>/.semantic-index/file-cache.json`

## MCP Tools

1. `graph_summary()`
2. `find_symbol(query, kind?, culture?, limit?)`
3. `get_callers(symbol_id, depth?)`
4. `get_callees(symbol_id, depth?)`
5. `impact_radius(target_id, target_type, depth?)`
6. `refactor_guardrail(symbol_id)`

## Culture Classification

Culture tags are derived from path and AST heuristics:

- `Auditor`: files under `Tests/` (or names ending in `*Test.swift` / `*Tests.swift`)
- `View`: files under `UI/` or `Views/`, or types/functions that look render-focused
- `Law`: files under `Config/`, `Configs/`, `Policy/`, or `Rules/`, plus config-like type names
- `Citizen`: default for everything else

## Development

Run tests:

```bash
python3 -m unittest discover -s semantic_index/tests -p 'test_*.py'
```

## Scope

This implementation is currently Swift-specific because parsing is built on `swiftc -dump-parse`.
It is repository-generic for Swift projects (no hardcoded repository names or filesystem paths).
