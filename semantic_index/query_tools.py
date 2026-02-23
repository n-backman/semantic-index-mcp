from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .schemas import (
    AMBIGUITY_CONFIDENCE_THRESHOLD,
    DEFAULT_IMPACT_DEPTH,
    EDGE_RESOLUTION_AMBIGUOUS,
    EDGE_RESOLUTION_EXTERNAL,
    EDGE_RESOLUTION_RESOLVED,
    LAW_HARD_BLOCK_CALLER_THRESHOLD,
    MAX_TOOL_NODES,
)


class GraphQueryEngine:
    def __init__(self, graph: dict[str, Any]) -> None:
        self.graph = graph
        self.symbol_by_id = {item["id"]: item for item in graph.get("symbols", [])}
        self.file_by_id = {item["id"]: item for item in graph.get("files", [])}
        self.impact_symbols = graph.get("impact", {}).get("symbols", {})

        self.edges_calls = graph.get("edges_calls", [])
        self.forward: dict[str, set[str]] = defaultdict(set)
        self.reverse: dict[str, set[str]] = defaultdict(set)

        for edge in self.edges_calls:
            if edge.get("resolution") != EDGE_RESOLUTION_RESOLVED:
                continue
            source = edge.get("source")
            target = edge.get("target")
            if source and target:
                self.forward[source].add(target)
                self.reverse[target].add(source)

        indexes = graph.get("indexes", {})
        self.symbols_by_name = indexes.get("symbols_by_name", {})
        self.symbols_by_file = indexes.get("symbols_by_file", {})
        self.files_by_role = indexes.get("files_by_role", {})

    @staticmethod
    def _truncate_nodes(nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        if len(nodes) <= MAX_TOOL_NODES:
            return nodes, False
        return nodes[:MAX_TOOL_NODES], True

    def graph_summary(self) -> dict[str, Any]:
        top_symbols = sorted(
            self.impact_symbols.items(),
            key=lambda item: (-item[1].get("score", 0), item[0]),
        )[:10]

        return {
            "schema_version": self.graph.get("meta", {}).get("schema_version"),
            "generated_at": self.graph.get("meta", {}).get("generated_at"),
            "repo_digest": self.graph.get("meta", {}).get("repo_digest"),
            "counts": {
                "files": len(self.graph.get("files", [])),
                "symbols": len(self.graph.get("symbols", [])),
                "edges_calls": len(self.graph.get("edges_calls", [])),
                "edges_mutations": len(self.graph.get("edges_mutations", [])),
                "edges_depends_on": len(self.graph.get("edges_depends_on", [])),
            },
            "hotspots": [
                {
                    "symbol_id": sid,
                    "score": metrics.get("score", 0),
                    "direct_callers": metrics.get("direct_callers", 0),
                }
                for sid, metrics in top_symbols
            ],
            "freshness": {
                "build_duration_ms": self.graph.get("meta", {}).get("build_duration_ms"),
                "files_reparsed": self.graph.get("meta", {}).get("files_reparsed"),
                "files_reused": self.graph.get("meta", {}).get("files_reused"),
            },
        }

    def find_symbol(
        self,
        query: str,
        kind: str | None = None,
        role: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        key = query.lower().strip()
        matched_ids: set[str] = set(self.symbols_by_name.get(key, []))

        if not matched_ids:
            for name, ids in self.symbols_by_name.items():
                if key in name:
                    matched_ids.update(ids)

        items: list[dict[str, Any]] = []
        for sid in sorted(matched_ids):
            symbol = self.symbol_by_id.get(sid)
            if not symbol:
                continue
            file_record = self.file_by_id.get(symbol["file"], {})
            symbol_role = file_record.get("role")
            if kind and symbol.get("kind") != kind:
                continue
            if role and symbol_role != role:
                continue
            confidence = 1.0 if symbol.get("name", "").lower() == key else 0.8
            items.append(
                {
                    "id": sid,
                    "name": symbol.get("name"),
                    "kind": symbol.get("kind"),
                    "signature": symbol.get("signature"),
                    "file": symbol.get("file"),
                    "line": symbol.get("line"),
                    "container": symbol.get("container"),
                    "visibility": symbol.get("visibility"),
                    "role": symbol_role,
                    "confidence": confidence,
                }
            )

        items.sort(key=lambda item: (-item["confidence"], item["name"], item["id"]))
        return {"query": query, "matches": items[:limit]}

    def _bfs(self, start: str, reverse: bool, depth: int) -> dict[str, int]:
        adjacency = self.reverse if reverse else self.forward
        distances: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        seen: set[str] = {start}

        while queue:
            node, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for nxt in adjacency.get(node, set()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                distances[nxt] = current_depth + 1
                queue.append((nxt, current_depth + 1))

        return distances

    def _symbol_payload(self, sid: str, distance: int) -> dict[str, Any]:
        symbol = self.symbol_by_id.get(sid)
        if symbol is None:
            return {
                "id": sid,
                "distance": distance,
                "error": "symbol not found in index",
            }
        file_record = self.file_by_id.get(symbol["file"], {})
        impact = self.impact_symbols.get(sid, {})
        return {
            "id": sid,
            "name": symbol.get("name"),
            "signature": symbol.get("signature"),
            "kind": symbol.get("kind"),
            "file": symbol.get("file"),
            "line": symbol.get("line"),
            "role": file_record.get("role"),
            "distance": distance,
            "impact_score": impact.get("score", 0),
        }

    def get_callers(self, symbol_id: str, depth: int = DEFAULT_IMPACT_DEPTH) -> dict[str, Any]:
        if symbol_id not in self.symbol_by_id:
            raise KeyError(f"unknown symbol_id: {symbol_id}")

        distances = self._bfs(symbol_id, reverse=True, depth=depth)
        nodes = [self._symbol_payload(sid, dist) for sid, dist in sorted(distances.items())]
        nodes.sort(key=lambda item: (item["distance"], -item["impact_score"], item["id"]))
        nodes, truncated = self._truncate_nodes(nodes)

        resolved = sum(
            1
            for edge in self.edges_calls
            if edge.get("resolution") == EDGE_RESOLUTION_RESOLVED
            and edge.get("target") == symbol_id
        )
        ambiguous = sum(
            1
            for edge in self.edges_calls
            if edge.get("resolution") == EDGE_RESOLUTION_AMBIGUOUS
            and symbol_id in edge.get("target_candidates", [])
        )

        return {
            "symbol_id": symbol_id,
            "depth": depth,
            "stats": {
                "resolved_edges": resolved,
                "ambiguous_edges": ambiguous,
                "external_edges": 0,
            },
            "nodes": nodes,
            "truncated": truncated,
        }

    def get_callees(self, symbol_id: str, depth: int = DEFAULT_IMPACT_DEPTH) -> dict[str, Any]:
        if symbol_id not in self.symbol_by_id:
            raise KeyError(f"unknown symbol_id: {symbol_id}")

        distances = self._bfs(symbol_id, reverse=False, depth=depth)
        nodes = [self._symbol_payload(sid, dist) for sid, dist in sorted(distances.items())]
        nodes.sort(key=lambda item: (item["distance"], -item["impact_score"], item["id"]))
        nodes, truncated = self._truncate_nodes(nodes)

        resolved = sum(
            1
            for edge in self.edges_calls
            if edge.get("resolution") == EDGE_RESOLUTION_RESOLVED
            and edge.get("source") == symbol_id
        )
        ambiguous = sum(
            1
            for edge in self.edges_calls
            if edge.get("resolution") == EDGE_RESOLUTION_AMBIGUOUS
            and edge.get("source") == symbol_id
        )
        external = sum(
            1
            for edge in self.edges_calls
            if edge.get("resolution") == EDGE_RESOLUTION_EXTERNAL
            and edge.get("source") == symbol_id
        )

        return {
            "symbol_id": symbol_id,
            "depth": depth,
            "stats": {
                "resolved_edges": resolved,
                "ambiguous_edges": ambiguous,
                "external_edges": external,
            },
            "nodes": nodes,
            "truncated": truncated,
        }

    def impact_radius(
        self,
        target_id: str,
        target_type: str,
        depth: int = DEFAULT_IMPACT_DEPTH,
    ) -> dict[str, Any]:
        if target_type not in {"symbol", "file"}:
            raise ValueError("target_type must be 'symbol' or 'file'")

        start_symbols: set[str] = set()
        if target_type == "symbol":
            if target_id not in self.symbol_by_id:
                raise KeyError(f"unknown symbol_id: {target_id}")
            start_symbols.add(target_id)
        else:
            for sid in self.symbols_by_file.get(target_id, []):
                start_symbols.add(sid)
            if not start_symbols:
                raise KeyError(f"unknown file id: {target_id}")

        distances: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque((sid, 0) for sid in sorted(start_symbols))
        seen: set[str] = set(start_symbols)

        while queue:
            node, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            neighbors = self.forward.get(node, set()) | self.reverse.get(node, set())
            for nxt in neighbors:
                if nxt in seen:
                    continue
                seen.add(nxt)
                distances[nxt] = current_depth + 1
                queue.append((nxt, current_depth + 1))

        nodes = []
        for sid, dist in sorted(distances.items()):
            payload = self._symbol_payload(sid, dist)
            score = payload["impact_score"]
            payload["influence"] = round(score / max(1, dist), 4)
            nodes.append(payload)

        nodes.sort(key=lambda item: (-item["influence"], item["distance"], item["id"]))
        nodes, truncated = self._truncate_nodes(nodes)

        touched_files = sorted({item["file"] for item in nodes})
        return {
            "target_id": target_id,
            "target_type": target_type,
            "depth": depth,
            "nodes": nodes,
            "files_touched": touched_files,
            "truncated": truncated,
        }

    def refactor_guardrail(self, symbol_id: str) -> dict[str, Any]:
        symbol = self.symbol_by_id.get(symbol_id)
        if not symbol:
            raise KeyError(f"unknown symbol_id: {symbol_id}")

        file_record = self.file_by_id.get(symbol["file"], {})
        role = file_record.get("role")
        metrics = self.impact_symbols.get(symbol_id, {})

        direct_callers = int(metrics.get("direct_callers", 0))
        fan_out = int(metrics.get("fan_out", 0))
        unresolved_count = int(metrics.get("unresolved_count", 0))
        unresolved_min_conf = float(metrics.get("unresolved_min_confidence", 1.0))

        guardrail = "allow_change_with_tests"
        reason = ""

        if role == "Auditor":
            guardrail = "auditor_advisory"
            reason = "Auditor symbols are excluded from hard signature blocks."
        elif unresolved_count > 0 and unresolved_min_conf < AMBIGUITY_CONFIDENCE_THRESHOLD:
            guardrail = "high_risk_manual_review"
            reason = (
                "Low-confidence ambiguous resolution detected; fail-closed policy requires "
                "manual review before refactor."
            )
        elif role == "Law" and direct_callers >= LAW_HARD_BLOCK_CALLER_THRESHOLD:
            guardrail = "hard_block_signature_change"
            reason = (
                "Law symbol exceeds caller threshold; signature changes are blocked by policy."
            )
        elif role == "View":
            guardrail = "view_soft_warn"
            reason = "View symbol: report impact radius and avoid broad cascading edits."
        elif direct_callers + fan_out >= 40:
            guardrail = "citizen_high_surface"
            reason = "High connectivity; stage refactor with compatibility shims."
        else:
            reason = "No hard policy triggers hit."

        return {
            "symbol_id": symbol_id,
            "symbol_name": symbol.get("name"),
            "signature": symbol.get("signature"),
            "role": role,
            "direct_callers": direct_callers,
            "depth2_callers": int(metrics.get("depth2_callers", 0)),
            "fan_out": fan_out,
            "unresolved_count": unresolved_count,
            "unresolved_min_confidence": unresolved_min_conf,
            "guardrail": guardrail,
            "hard_block": guardrail == "hard_block_signature_change",
            "message": (
                f"{symbol.get('name')} is classified as {role} with {direct_callers} direct callers; "
                f"guardrail={guardrail}."
            ),
            "reason": reason,
            "do": [
                "Use impact_radius before editing connected symbols.",
                "Prefer additive changes over signature breaks.",
                "Run focused tests on touched reducers/views.",
            ],
            "dont": [
                "Do not change signatures when hard_block is true.",
                "Do not ignore ambiguous-call warnings.",
            ],
        }

    def pre_edit_check(
        self,
        query: str,
        kind: str | None = None,
        depth: int = DEFAULT_IMPACT_DEPTH,
    ) -> dict[str, Any]:
        matches = self.find_symbol(query=query, kind=kind).get("matches", [])
        container_query = ""
        if "." in query:
            container_query, _, symbol_query = query.rpartition(".")
            fallback_matches = self.find_symbol(query=symbol_query, kind=kind).get("matches", [])
            if fallback_matches:
                matches = [
                    item
                    for item in fallback_matches
                    if self._container_matches(item.get("container"), container_query)
                ]

        if not matches:
            payload: dict[str, Any] = {"status": "no_match", "query": query}
            if kind:
                payload["kind"] = kind
            return payload

        top_confidence = matches[0].get("confidence", 0.0)
        top_candidates = [
            item for item in matches if item.get("confidence", 0.0) == top_confidence
        ]
        if len(top_candidates) != 1:
            payload = {
                "status": "ambiguous",
                "query": query,
                "candidates": top_candidates[:10],
            }
            if kind:
                payload["kind"] = kind
            return payload

        symbol = top_candidates[0]
        symbol_id = symbol["id"]

        guardrail = self.refactor_guardrail(symbol_id)
        impact = self.impact_radius(target_id=symbol_id, target_type="symbol", depth=depth)
        callers = self.get_callers(symbol_id=symbol_id, depth=depth)
        caller_stats = callers.get("stats", {})

        return {
            "status": "resolved",
            "symbol": {
                "id": symbol.get("id"),
                "name": symbol.get("name"),
                "kind": symbol.get("kind"),
                "signature": symbol.get("signature"),
                "file": symbol.get("file"),
                "line": symbol.get("line"),
                "role": symbol.get("role"),
                "confidence": symbol.get("confidence"),
            },
            "guardrail": {
                "decision": guardrail.get("guardrail"),
                "hard_block": guardrail.get("hard_block"),
                "message": guardrail.get("message"),
                "reason": guardrail.get("reason"),
                "direct_callers": guardrail.get("direct_callers"),
                "depth2_callers": guardrail.get("depth2_callers"),
                "do": guardrail.get("do"),
                "dont": guardrail.get("dont"),
            },
            "impact": {
                "files_touched": impact.get("files_touched", []),
                "node_count": len(impact.get("nodes", [])),
                "top_nodes": impact.get("nodes", [])[:10],
            },
            "callers": {
                "resolved_edges": caller_stats.get("resolved_edges", 0),
                "ambiguous_edges": caller_stats.get("ambiguous_edges", 0),
                "nodes": callers.get("nodes", [])[:15],
            },
        }

    @staticmethod
    def _container_matches(symbol_container: Any, query_container: str) -> bool:
        if not symbol_container or not query_container:
            return False

        symbol_value = str(symbol_container).lower()
        query_value = query_container.lower()
        return (
            symbol_value == query_value
            or symbol_value.endswith(f".{query_value}")
            or query_value.endswith(f".{symbol_value}")
        )


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "graph_summary",
            "description": "Return graph counts, hotspot leaders, and freshness metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "find_symbol",
            "description": "Lookup symbols by name with optional kind and role filters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "kind": {"type": "string"},
                    "role": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_callers",
            "description": "Return caller slice for a symbol up to depth 2.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol_id": {"type": "string"},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 2},
                },
                "required": ["symbol_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_callees",
            "description": "Return callee slice for a symbol up to depth 2.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol_id": {"type": "string"},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 2},
                },
                "required": ["symbol_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "impact_radius",
            "description": "Compute blast radius for a symbol or file at bounded traversal depth.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "string"},
                    "target_type": {"type": "string", "enum": ["symbol", "file"]},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 2},
                },
                "required": ["target_id", "target_type"],
                "additionalProperties": False,
            },
        },
        {
            "name": "refactor_guardrail",
            "description": "Return risk policy decision and do/don't guidance for a symbol.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol_id": {"type": "string"},
                },
                "required": ["symbol_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "pre_edit_check",
            "description": (
                "Resolve a symbol query and return guardrail, impact, and caller context "
                "for safe edits."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "kind": {"type": "string"},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 2},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    ]
