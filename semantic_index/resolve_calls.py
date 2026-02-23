from __future__ import annotations

from collections import defaultdict
from typing import Any

from .schemas import (
    EDGE_RESOLUTION_AMBIGUOUS,
    EDGE_RESOLUTION_EXTERNAL,
    EDGE_RESOLUTION_RESOLVED,
    SYMBOL_KIND_FUNCTION,
)


def _index_functions(symbols: list[dict[str, Any]]) -> dict[str, Any]:
    by_name_arity: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    by_container_name_arity: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_container_name: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for symbol in symbols:
        if symbol.get("kind") != SYMBOL_KIND_FUNCTION:
            continue
        name = symbol.get("name", "")
        arity = int(symbol.get("arity", 0))
        container = symbol.get("container", "global")

        by_name_arity[(name, arity)].append(symbol)
        by_container_name_arity[(container, name, arity)].append(symbol)
        by_name[name].append(symbol)
        by_container_name[(container, name)].append(symbol)

    return {
        "by_name_arity": by_name_arity,
        "by_container_name_arity": by_container_name_arity,
        "by_name": by_name,
        "by_container_name": by_container_name,
    }


def _pick_candidates(
    call: dict[str, Any],
    index: dict[str, Any],
) -> list[dict[str, Any]]:
    callee_name = call.get("callee_name", "")
    arity = int(call.get("arity", 0))
    qualifier = call.get("qualifier")

    if qualifier:
        candidates = index["by_container_name_arity"].get((qualifier, callee_name, arity), [])
        if candidates:
            return candidates
        candidates = index["by_container_name"].get((qualifier, callee_name), [])
        if candidates:
            return candidates

    candidates = index["by_name_arity"].get((callee_name, arity), [])
    if candidates:
        return candidates

    return index["by_name"].get(callee_name, [])


def resolve_calls(
    symbols: list[dict[str, Any]],
    calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    index = _index_functions(symbols)
    edges: list[dict[str, Any]] = []

    for call in calls:
        source_symbol_id = call.get("source_symbol_id")
        candidates = _pick_candidates(call, index)
        callee_name = call.get("callee_name")
        qualifier = call.get("qualifier")

        if len(candidates) == 1:
            target = candidates[0]
            edges.append(
                {
                    "source": source_symbol_id,
                    "target": target["id"],
                    "target_name": callee_name,
                    "target_candidates": [target["id"]],
                    "resolution": EDGE_RESOLUTION_RESOLVED,
                    "confidence": 1.0,
                    "qualifier": qualifier,
                    "arity": int(call.get("arity", 0)),
                    "line": int(call.get("line", 0)),
                }
            )
            continue

        if len(candidates) > 1:
            candidate_ids = sorted(item["id"] for item in candidates)
            confidence = max(0.1, round(1.0 / len(candidate_ids), 4))
            edges.append(
                {
                    "source": source_symbol_id,
                    "target": None,
                    "target_name": callee_name,
                    "target_candidates": candidate_ids,
                    "resolution": EDGE_RESOLUTION_AMBIGUOUS,
                    "confidence": confidence,
                    "qualifier": qualifier,
                    "arity": int(call.get("arity", 0)),
                    "line": int(call.get("line", 0)),
                }
            )
            continue

        edges.append(
            {
                "source": source_symbol_id,
                "target": None,
                "target_name": callee_name,
                "target_candidates": [],
                "resolution": EDGE_RESOLUTION_EXTERNAL,
                "confidence": 0.0,
                "qualifier": qualifier,
                "arity": int(call.get("arity", 0)),
                "line": int(call.get("line", 0)),
            }
        )

    edges.sort(
        key=lambda item: (
            item["source"],
            item["resolution"],
            item["target"] or "",
            item["target_name"],
            item["line"],
        )
    )
    return edges
