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
python3 semantic_index/cli.py --repo-root /path/to/your/repo watch --bootstrap-index
```

Index sibling Swift repos into one workspace graph by repeating `--root`:

```bash
python3 semantic_index/cli.py \
  --repo-root /path/to/app-repo \
  --root /path/to/shared-library-a \
  --root /path/to/shared-library-b \
  build
```

## How It Works

The system has four distinct modes:

1. Build

```bash
python3 semantic_index/cli.py --repo-root /path/to/repo build
```

This performs a full parse of all Swift files in the workspace and writes a graph plus cache.
Use this the first time you index a repo or when you want a clean rebuild.

2. Refresh

```bash
python3 semantic_index/cli.py --repo-root /path/to/repo refresh
```

This performs an incremental update using the file cache. Unchanged files are reused and only changed files are reparsed.
Use this after edits, pulls, branch switches, or generated-code updates.

3. Watch

```bash
python3 semantic_index/cli.py --repo-root /path/to/repo watch --bootstrap-index
```

This starts a long-running local watcher. On startup it builds or refreshes the graph once, then it polls the workspace for Swift file changes and keeps the graph current in the background.
Use this when you want the graph to behave like a persistent local index.

4. Serve MCP

```bash
python3 semantic_index/cli.py --repo-root /path/to/repo serve-mcp
```

This starts the stdio MCP server. It does not create a separate HTTP service; instead, MCP clients launch the process and talk to it over stdin/stdout.
Use this when wiring the server into Claude Code, Codex, or another stdio-capable MCP client.

## Common Workflows

Build once, then serve:

```bash
python3 semantic_index/cli.py --repo-root /path/to/repo build
python3 semantic_index/cli.py --repo-root /path/to/repo serve-mcp
```

Run a persistent watcher locally, then serve the already-built graph from another process:

```bash
python3 semantic_index/cli.py --repo-root /path/to/repo watch --bootstrap-index
python3 semantic_index/cli.py --repo-root /path/to/repo serve-mcp
```

Index a multi-repo workspace:

```bash
python3 semantic_index/cli.py \
  --repo-root /path/to/app-repo \
  --root /path/to/shared-library-a \
  --root /path/to/shared-library-b \
  watch --bootstrap-index
```

Observe the current graph state:

```bash
python3 semantic_index/cli.py --repo-root /path/to/repo doctor --strict
```

Or connect through MCP and call:

- `graph_summary()`
- `find_symbol(...)`
- `pre_edit_check(...)`
- `get_callers(...)`
- `get_callees(...)`
- `impact_radius(...)`

## Docker

Build the image:

```bash
docker build -t semantic-index-mcp .
```

Run the MCP server over stdio against a mounted target repo:

```bash
docker run --rm -i \
  -e REPO_ROOT=/repo \
  -e SEMANTIC_INDEX_STATE_DIR=/state \
  -e SEMANTIC_INDEX_REPO_KEY=your-repo-name \
  -v /absolute/path/to/your/repo:/repo \
  -v semantic-index-state:/state \
  semantic-index-mcp
```

The container now defaults to:

```bash
python3 semantic_index/cli.py \
  --repo-root /absolute/path/to/your/repo \
  --state-dir /state \
  serve-mcp --bootstrap-index --watch --watch-interval 2.0
```

On startup it builds the graph if missing or refreshes it if state already exists. After that it polls the mounted repo for Swift file changes and runs incremental refreshes in the background. Graph and cache state are stored outside the repo in `/state`, and `SEMANTIC_INDEX_REPO_KEY` lets one flat Docker volume keep separate cache directories for multiple repositories even when they are all mounted at `/repo`.

For Apple-platform Swift repos that depend on frameworks such as `SwiftUI`, host-native indexing is usually the safer choice. In that setup, run `build`, `refresh`, or `watch` on the host Mac and use Docker only for `serve-mcp` if you still want a containerized MCP process.

You can still run explicit index commands:

```bash
docker run --rm \
  -e REPO_ROOT=/repo \
  -e SEMANTIC_INDEX_STATE_DIR=/state \
  -e SEMANTIC_INDEX_REPO_KEY=your-repo-name \
  -v /absolute/path/to/your/repo:/repo \
  -v semantic-index-state:/state \
  semantic-index-mcp build
```

## Claude / Codex MCP Config

This server uses stdio MCP, so the simplest integration is to have Claude Code or Codex launch `docker run` directly.

Example Claude `.mcp.json`:

```json
{
  "mcpServers": {
    "semantic-index": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-e",
        "REPO_ROOT=/repo",
        "-e",
        "SEMANTIC_INDEX_STATE_DIR=/state",
        "-e",
        "SEMANTIC_INDEX_REPO_KEY=your-repo-name",
        "-v",
        "/absolute/path/to/your/repo:/repo",
        "-v",
        "semantic-index-state:/state",
        "semantic-index-mcp"
      ]
    }
  }
}
```

For Codex, add a custom stdio MCP server that uses the same command and args:

- command: `docker`
- args: `run`, `--rm`, `-i`, `-e`, `REPO_ROOT=/repo`, `-e`, `SEMANTIC_INDEX_STATE_DIR=/state`, `-e`, `SEMANTIC_INDEX_REPO_KEY=your-repo-name`, `-v`, `/absolute/path/to/your/repo:/repo`, `-v`, `semantic-index-state:/state`, `semantic-index-mcp`

If you want to disable background refresh for a given run, override the container command and omit `--watch`.

## Graph Outputs

By default, artifacts are written into the target repo:

- `<repo>/.semantic-index/graph.json`
- `<repo>/.semantic-index/file-cache.json`

If you pass `--state-dir` or set `SEMANTIC_INDEX_STATE_DIR`, artifacts are written under that state root instead, optionally namespaced by `SEMANTIC_INDEX_REPO_KEY`.

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
It is repository-generic for Swift projects. Public documentation and examples should use placeholder paths, not machine-specific filesystem paths.
