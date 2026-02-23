from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .graph_store import graph_path, load_graph
from .query_tools import GraphQueryEngine, tool_definitions

JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self._engine: GraphQueryEngine | None = None
        self._graph_mtime_ns: int | None = None

    def _reload_engine_if_needed(self) -> GraphQueryEngine:
        path = graph_path(self.repo_root)
        if not path.exists():
            raise FileNotFoundError(f"graph file not found: {path}")

        stat = path.stat()
        mtime_ns = stat.st_mtime_ns
        if self._engine is None or self._graph_mtime_ns != mtime_ns:
            graph = load_graph(self.repo_root)
            if graph is None:
                raise RuntimeError("unable to load graph file")
            self._engine = GraphQueryEngine(graph)
            self._graph_mtime_ns = mtime_ns
        return self._engine

    def _success(self, request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}

    def _error(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}

    @staticmethod
    def _tool_payload(payload: Any, is_error: bool = False) -> dict[str, Any]:
        return {
            "isError": is_error,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, sort_keys=True),
                }
            ],
        }

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params", {}) or {}

        if method == "initialize":
            return self._success(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {
                        "name": "semantic-index-mcp",
                        "version": "1.0.0",
                    },
                    "capabilities": {
                        "tools": {},
                    },
                },
            )

        if method == "notifications/initialized":
            return None

        if method == "ping":
            return self._success(request_id, {"ok": True})

        if method == "tools/list":
            return self._success(request_id, {"tools": tool_definitions()})

        if method == "tools/call":
            try:
                engine = self._reload_engine_if_needed()
                name = params.get("name")
                arguments = params.get("arguments", {}) or {}

                if name == "graph_summary":
                    result = engine.graph_summary()
                elif name == "find_symbol":
                    result = engine.find_symbol(
                        query=arguments["query"],
                        kind=arguments.get("kind"),
                        culture=arguments.get("culture"),
                        limit=int(arguments.get("limit", 25)),
                    )
                elif name == "get_callers":
                    result = engine.get_callers(
                        symbol_id=arguments["symbol_id"],
                        depth=int(arguments.get("depth", 2)),
                    )
                elif name == "get_callees":
                    result = engine.get_callees(
                        symbol_id=arguments["symbol_id"],
                        depth=int(arguments.get("depth", 2)),
                    )
                elif name == "impact_radius":
                    result = engine.impact_radius(
                        target_id=arguments["target_id"],
                        target_type=arguments["target_type"],
                        depth=int(arguments.get("depth", 2)),
                    )
                elif name == "refactor_guardrail":
                    result = engine.refactor_guardrail(symbol_id=arguments["symbol_id"])
                else:
                    return self._success(
                        request_id,
                        self._tool_payload({"error": f"unknown tool: {name}"}, is_error=True),
                    )

                return self._success(request_id, self._tool_payload(result, is_error=False))
            except Exception as exc:  # pragma: no cover - exercised in integration
                return self._success(
                    request_id,
                    self._tool_payload({"error": str(exc)}, is_error=True),
                )

        return self._error(request_id, -32601, f"Method not found: {method}")


def _read_message(stdin: Any) -> dict[str, Any] | None:
    header_lines: list[str] = []
    while True:
        line = stdin.readline()
        if line == b"":
            return None
        if line in (b"\r\n", b"\n"):
            break
        header_lines.append(line.decode("utf-8", errors="ignore").strip())

    content_length = None
    for line in header_lines:
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())
            break

    if content_length is None:
        if header_lines:
            raw = "\n".join(header_lines)
            return json.loads(raw)
        return None

    payload = stdin.read(content_length)
    if not payload:
        return None
    return json.loads(payload.decode("utf-8"))


def _write_message(stdout: Any, message: dict[str, Any]) -> None:
    data = json.dumps(message, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
    stdout.write(header)
    stdout.write(data)
    stdout.flush()


def serve(repo_root: Path) -> int:
    server = MCPServer(repo_root)

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        request = _read_message(stdin)
        if request is None:
            break
        response = server.handle_request(request)
        if response is not None and "id" in response:
            _write_message(stdout, response)

    return 0
