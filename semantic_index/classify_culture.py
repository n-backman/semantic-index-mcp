from __future__ import annotations

from typing import Any

from .schemas import CULTURE_AUDITOR, CULTURE_CITIZEN, CULTURE_LAW, CULTURE_VIEW


def classify_file(rel_path: str, analysis: dict[str, Any]) -> str:
    normalized = rel_path.replace("\\", "/")
    lower_path = normalized.lower()

    # Path heuristics intended to work across arbitrary repository layouts.
    if (
        "/tests/" in lower_path
        or lower_path.startswith("tests/")
        or lower_path.endswith("tests.swift")
        or lower_path.endswith("test.swift")
    ):
        return CULTURE_AUDITOR
    if (
        "/ui/" in lower_path
        or "/views/" in lower_path
        or lower_path.startswith("ui/")
        or lower_path.startswith("views/")
    ):
        return CULTURE_VIEW
    if (
        "/config/" in lower_path
        or "/configs/" in lower_path
        or "/policy/" in lower_path
        or "/rules/" in lower_path
        or lower_path.startswith("config/")
        or lower_path.startswith("configs/")
    ):
        return CULTURE_LAW

    # AST fallback rules for ambiguous/unusual paths.
    type_names = [item.get("name", "") for item in analysis.get("types", [])]
    func_names = [item.get("name", "") for item in analysis.get("functions", [])]

    if any(name.endswith("Tests") for name in type_names):
        return CULTURE_AUDITOR

    if any(name.endswith("Config") or name.endswith("Constants") for name in type_names):
        return CULTURE_LAW

    lower_funcs = {name.lower() for name in func_names}
    if {"body", "makeui", "render"} & lower_funcs:
        return CULTURE_VIEW

    return CULTURE_CITIZEN


def culture_multiplier(culture: str) -> float:
    if culture == CULTURE_LAW:
        return 1.4
    if culture == CULTURE_VIEW:
        return 0.8
    if culture == CULTURE_AUDITOR:
        return 0.2
    return 1.0
