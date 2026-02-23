#!/bin/sh
set -eu

REPO_ROOT="${REPO_ROOT:-/repo}"
STATE_DIR="${SEMANTIC_INDEX_STATE_DIR:-}"

if [ "$#" -eq 0 ]; then
  set -- serve-mcp --bootstrap-index --watch --watch-interval 2.0
fi

if [ -n "$STATE_DIR" ]; then
  set -- --state-dir "$STATE_DIR" "$@"
fi

exec python3 -u /app/semantic_index/cli.py --repo-root "$REPO_ROOT" "$@"
