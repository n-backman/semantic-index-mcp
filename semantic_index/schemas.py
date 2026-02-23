from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "1.0.0"
PARSER_VERSION = "swiftc-dump-parse-v1"
CACHE_VERSION = "1.0.0"

GRAPH_DIRNAME = ".semantic-index"
GRAPH_FILENAME = "graph.json"
CACHE_FILENAME = "file-cache.json"

DEFAULT_IMPACT_DEPTH = 2
LAW_HARD_BLOCK_CALLER_THRESHOLD = 100
AMBIGUITY_CONFIDENCE_THRESHOLD = 0.75

CULTURE_VIEW = "View"
CULTURE_LAW = "Law"
CULTURE_AUDITOR = "Auditor"
CULTURE_CITIZEN = "Citizen"
VALID_CULTURES = {
    CULTURE_VIEW,
    CULTURE_LAW,
    CULTURE_AUDITOR,
    CULTURE_CITIZEN,
}

SYMBOL_KIND_TYPE = "type"
SYMBOL_KIND_FUNCTION = "function"
SYMBOL_KIND_VARIABLE = "variable"
VALID_SYMBOL_KINDS = {SYMBOL_KIND_TYPE, SYMBOL_KIND_FUNCTION, SYMBOL_KIND_VARIABLE}

EDGE_RESOLUTION_RESOLVED = "resolved"
EDGE_RESOLUTION_AMBIGUOUS = "ambiguous"
EDGE_RESOLUTION_EXTERNAL = "external"
VALID_EDGE_RESOLUTIONS = {
    EDGE_RESOLUTION_RESOLVED,
    EDGE_RESOLUTION_AMBIGUOUS,
    EDGE_RESOLUTION_EXTERNAL,
}

VISIBILITY_PUBLIC = "public"
VISIBILITY_OPEN = "open"
PUBLIC_VISIBILITIES = {VISIBILITY_PUBLIC, VISIBILITY_OPEN}


@dataclass(frozen=True)
class BuildStats:
    files_total: int
    files_reparsed: int
    files_reused: int
    symbols_total: int
    call_edges_total: int
    mutation_edges_total: int
    duration_ms: int


def is_public_visibility(value: str) -> bool:
    return value in PUBLIC_VISIBILITIES


def graph_top_level_keys() -> list[str]:
    return [
        "meta",
        "files",
        "symbols",
        "edges_calls",
        "edges_mutations",
        "edges_depends_on",
        "impact",
        "indexes",
    ]


def validate_graph_shape(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in graph_top_level_keys():
        if key not in graph:
            errors.append(f"missing top-level key: {key}")

    schema = graph.get("meta", {}).get("schema_version")
    if schema != SCHEMA_VERSION:
        errors.append(
            f"schema_version mismatch: expected {SCHEMA_VERSION}, got {schema!r}"
        )

    symbols = graph.get("symbols")
    if not isinstance(symbols, list):
        errors.append("symbols must be a list")
    edges_calls = graph.get("edges_calls")
    if not isinstance(edges_calls, list):
        errors.append("edges_calls must be a list")
    files = graph.get("files")
    if not isinstance(files, list):
        errors.append("files must be a list")

    return errors
