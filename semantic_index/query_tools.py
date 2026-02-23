from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .schemas import (
    AMBIGUITY_CONFIDENCE_THRESHOLD,
    CULTURE_AUDITOR,
    CULTURE_LAW,
    CULTURE_VIEW,
    DEFAULT_IMPACT_DEPTH,
    EDGE_RESOLUTION_AMBIGUOUS,
    EDGE_RESOLUTION_EXTERNAL,
    EDGE_RESOLUTION_RESOLVED,
    LAW_HARD_BLOCK_CALLER_THRESHOLD,
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
        self.files_by_culture = indexes.get("files_by_culture", {})

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
        culture: str | None = None,
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
            symbol_culture = file_record.get("culture", "Citizen")
            if kind and symbol.get("kind") != kind:
                continue
            if culture and symbol_culture != culture:
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
                    "culture": symbol_culture,
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
        symbol = self.symbol_by_id[sid]
        file_record = self.file_by_id.get(symbol["file"], {})
        impact = self.impact_symbols.get(sid, {})
        return {
            "id": sid,
            "name": symbol.get("name"),
            "signature": symbol.get("signature"),
            "kind": symbol.get("kind"),
            "file": symbol.get("file"),
            "line": symbol.get("line"),
            "culture": file_record.get("culture", "Citizen"),
            "distance": distance,
            "impact_score": impact.get("score", 0),
        }

    def get_callers(self, symbol_id: str, depth: int = DEFAULT_IMPACT_DEPTH) -> dict[str, Any]:
        if symbol_id not in self.symbol_by_id:
            raise KeyError(f"unknown symbol_id: {symbol_id}")

        distances = self._bfs(symbol_id, reverse=True, depth=depth)
        nodes = [self._symbol_payload(sid, dist) for sid, dist in sorted(distances.items())]
        nodes.sort(key=lambda item: (item["distance"], -item["impact_score"], item["id"]))

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
        }

    def get_callees(self, symbol_id: str, depth: int = DEFAULT_IMPACT_DEPTH) -> dict[str, Any]:
        if symbol_id not in self.symbol_by_id:
            raise KeyError(f"unknown symbol_id: {symbol_id}")

        distances = self._bfs(symbol_id, reverse=False, depth=depth)
        nodes = [self._symbol_payload(sid, dist) for sid, dist in sorted(distances.items())]
        nodes.sort(key=lambda item: (item["distance"], -item["impact_score"], item["id"]))

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

        touched_files = sorted({item["file"] for item in nodes})
        return {
            "target_id": target_id,
            "target_type": target_type,
            "depth": depth,
            "nodes": nodes,
            "files_touched": touched_files,
        }

    def refactor_guardrail(self, symbol_id: str) -> dict[str, Any]:
        symbol = self.symbol_by_id.get(symbol_id)
        if not symbol:
            raise KeyError(f"unknown symbol_id: {symbol_id}")

        file_record = self.file_by_id.get(symbol["file"], {})
        culture = file_record.get("culture", "Citizen")
        metrics = self.impact_symbols.get(symbol_id, {})

        direct_callers = int(metrics.get("direct_callers", 0))
        fan_out = int(metrics.get("fan_out", 0))
        unresolved_count = int(metrics.get("unresolved_count", 0))
        unresolved_min_conf = float(metrics.get("unresolved_min_confidence", 1.0))

        guardrail = "allow_change_with_tests"
        reason = ""

        if culture == CULTURE_AUDITOR:
            guardrail = "auditor_advisory"
            reason = "Auditor symbols are excluded from hard signature blocks."
        elif unresolved_count > 0 and unresolved_min_conf < AMBIGUITY_CONFIDENCE_THRESHOLD:
            guardrail = "high_risk_manual_review"
            reason = (
                "Low-confidence ambiguous resolution detected; fail-closed policy requires "
                "manual review before refactor."
            )
        elif culture == CULTURE_LAW and direct_callers >= LAW_HARD_BLOCK_CALLER_THRESHOLD:
            guardrail = "hard_block_signature_change"
            reason = (
                "Law symbol exceeds caller threshold; signature changes are blocked by policy."
            )
        elif culture == CULTURE_VIEW:
            guardrail = "view_soft_warn"
            reason = "View symbol: report impact radius and avoid broad cascading edits."
        elif direct_callers + fan_out >= 40:
            guardrail = "citizen_high_surface"
            reason = "Citizen symbol has high connectivity; stage refactor with compatibility shims."
        else:
            reason = "No hard policy triggers hit."

        return {
            "symbol_id": symbol_id,
            "symbol_name": symbol.get("name"),
            "signature": symbol.get("signature"),
            "culture": culture,
            "direct_callers": direct_callers,
            "depth2_callers": int(metrics.get("depth2_callers", 0)),
            "fan_out": fan_out,
            "unresolved_count": unresolved_count,
            "unresolved_min_confidence": unresolved_min_conf,
            "guardrail": guardrail,
            "hard_block": guardrail == "hard_block_signature_change",
            "message": (
                f"{symbol.get('name')} is classified as {culture} with {direct_callers} direct callers; "
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
            "description": "Lookup symbols by name with optional kind and culture filters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "kind": {"type": "string"},
                    "culture": {"type": "string"},
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
    ]
