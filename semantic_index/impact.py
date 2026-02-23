from __future__ import annotations

from collections import defaultdict, deque
from statistics import mean
from typing import Any

from .classify_culture import culture_multiplier
from .schemas import EDGE_RESOLUTION_AMBIGUOUS, EDGE_RESOLUTION_EXTERNAL, is_public_visibility


def _reverse_reachable_depth_two(
    target: str,
    reverse_edges: dict[str, set[str]],
) -> set[str]:
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(target, 0)])

    while queue:
        node, depth = queue.popleft()
        if depth >= 2:
            continue
        for caller in reverse_edges.get(node, set()):
            if caller in seen:
                continue
            seen.add(caller)
            queue.append((caller, depth + 1))

    return seen


def compute_impact(
    symbols: list[dict[str, Any]],
    edges_calls: list[dict[str, Any]],
    edges_mutations: list[dict[str, Any]],
    culture_by_file: dict[str, str],
) -> dict[str, Any]:
    symbol_ids = {symbol["id"] for symbol in symbols}

    callers: dict[str, set[str]] = defaultdict(set)
    callees: dict[str, set[str]] = defaultdict(set)
    unresolved_outbound: dict[str, list[float]] = defaultdict(list)
    unresolved_inbound: dict[str, list[float]] = defaultdict(list)

    for edge in edges_calls:
        source = edge.get("source")
        resolution = edge.get("resolution")
        target = edge.get("target")

        if resolution == "resolved" and source and target:
            callers[target].add(source)
            callees[source].add(target)
        elif resolution in {EDGE_RESOLUTION_AMBIGUOUS, EDGE_RESOLUTION_EXTERNAL} and source:
            unresolved_outbound[source].append(float(edge.get("confidence", 0.0)))
            for candidate in edge.get("target_candidates", []):
                unresolved_inbound[candidate].append(float(edge.get("confidence", 0.0)))

    mutation_count_by_symbol: dict[str, int] = defaultdict(int)
    for edge in edges_mutations:
        source = edge.get("source")
        if source:
            mutation_count_by_symbol[source] += 1

    symbol_metrics: dict[str, dict[str, Any]] = {}

    for symbol in symbols:
        sid = symbol["id"]
        file_path = symbol["file"]
        culture = culture_by_file.get(file_path, "Citizen")
        direct_callers = len(callers.get(sid, set()))
        depth2_callers = len(_reverse_reachable_depth_two(sid, callers))
        fan_out = len(callees.get(sid, set()))
        mutation_count = mutation_count_by_symbol.get(sid, 0)
        mutation_density = round(mutation_count / max(1, fan_out + 1), 4)
        public_api = is_public_visibility(symbol.get("visibility", "internal"))
        unresolved_scores = unresolved_outbound.get(sid, []) + unresolved_inbound.get(sid, [])
        unresolved_count = len(unresolved_scores)
        unresolved_mean_confidence = round(mean(unresolved_scores), 4) if unresolved_scores else 1.0
        unresolved_min_confidence = round(min(unresolved_scores), 4) if unresolved_scores else 1.0

        base_score = (
            direct_callers * 1.0
            + depth2_callers * 0.5
            + fan_out * 0.7
            + mutation_count * 0.35
            + (2.0 if public_api else 0.0)
        )
        score = round(base_score * culture_multiplier(culture), 4)

        symbol_metrics[sid] = {
            "direct_callers": direct_callers,
            "depth2_callers": depth2_callers,
            "fan_out": fan_out,
            "mutation_count": mutation_count,
            "mutation_density": mutation_density,
            "public_api": public_api,
            "culture_multiplier": culture_multiplier(culture),
            "score": score,
            "unresolved_count": unresolved_count,
            "unresolved_mean_confidence": unresolved_mean_confidence,
            "unresolved_min_confidence": unresolved_min_confidence,
        }

    symbols_by_file: dict[str, list[str]] = defaultdict(list)
    for symbol in symbols:
        symbols_by_file[symbol["file"]].append(symbol["id"])

    file_metrics: dict[str, dict[str, Any]] = {}
    for file_path, sids in symbols_by_file.items():
        scores = [symbol_metrics[sid]["score"] for sid in sids if sid in symbol_metrics]
        direct = [symbol_metrics[sid]["direct_callers"] for sid in sids if sid in symbol_metrics]
        depth2 = [symbol_metrics[sid]["depth2_callers"] for sid in sids if sid in symbol_metrics]
        unresolved = [symbol_metrics[sid]["unresolved_count"] for sid in sids if sid in symbol_metrics]

        file_metrics[file_path] = {
            "symbol_count": len(sids),
            "aggregate_score": round(sum(scores), 4),
            "max_symbol_score": round(max(scores), 4) if scores else 0.0,
            "total_direct_callers": int(sum(direct)),
            "total_depth2_callers": int(sum(depth2)),
            "total_unresolved": int(sum(unresolved)),
        }

    return {
        "symbols": {key: symbol_metrics[key] for key in sorted(symbol_metrics)},
        "files": {key: file_metrics[key] for key in sorted(file_metrics)},
    }


def build_dependency_edges(
    symbols_by_id: dict[str, dict[str, Any]],
    edges_calls: list[dict[str, Any]],
) -> list[dict[str, str]]:
    edges: set[tuple[str, str]] = set()

    for edge in edges_calls:
        if edge.get("resolution") != "resolved":
            continue
        source = edge.get("source")
        target = edge.get("target")
        if not source or not target:
            continue
        source_symbol = symbols_by_id.get(source)
        target_symbol = symbols_by_id.get(target)
        if not source_symbol or not target_symbol:
            continue
        source_file = source_symbol["file"]
        target_file = target_symbol["file"]
        if source_file != target_file:
            edges.add((source_file, target_file))

    out = [
        {
            "source_file": source,
            "target_file": target,
            "reason": "call",
        }
        for source, target in sorted(edges)
    ]
    return out
