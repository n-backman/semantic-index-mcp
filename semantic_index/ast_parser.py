from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any

from .schemas import PARSER_VERSION, SYMBOL_KIND_FUNCTION, SYMBOL_KIND_TYPE, SYMBOL_KIND_VARIABLE

TYPE_DECL_RE = re.compile(
    r'\((class_decl|struct_decl|enum_decl|protocol_decl|actor_decl|typealias_decl)\b.*range=\[[^:]+:(\d+):\d+ - line:(\d+):\d+\]\s+"([^"]+)"'
)
FUNC_DECL_RE = re.compile(
    r'\(func_decl\b.*range=\[[^:]+:(\d+):\d+ - line:(\d+):\d+\]\s+"([^"]+)"'
)
VAR_DECL_RE = re.compile(
    r'\(var_decl\b.*range=\[[^:]+:(\d+):\d+ - line:(\d+):\d+\]\s+"([^"]+)"(?:\s+(let|var))?'
)
UNRESOLVED_DOT_RE = re.compile(r'unresolved_dot_expr[^\n]*field="([A-Za-z_][A-Za-z0-9_]*)"')
UNRESOLVED_MEMBER_RE = re.compile(
    r'unresolved_member_expr[^\n]*name="([A-Za-z_][A-Za-z0-9_]*)"'
)
UNRESOLVED_DECL_RE = re.compile(
    r'unresolved_decl_ref_expr[^\n]*name="([A-Za-z_][A-Za-z0-9_]*)"'
)
DECLREF_DECL_RE = re.compile(r'declref_expr[^\n]*decl="([^"]+)"')
RANGE_LINE_RE = re.compile(r'range=\[[^:]+:(\d+):\d+')
LABELS_RE = re.compile(r'labels="([^"]*)"')
ACCESS_RE = re.compile(r'\b(public|private|fileprivate|internal|open)\b')

_CALL_IGNORE_NAMES = {
    "self",
    "state",
    "config",
    "newState",
    "result",
    "lhs",
    "rhs",
    "value",
}


class ParseError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def run_dump_parse(file_path: Path) -> str:
    proc = subprocess.run(
        ["swiftc", "-typecheck", "-dump-parse", str(file_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ParseError(
            f"swiftc -typecheck -dump-parse failed for {file_path}: {proc.stderr.strip()}"
        )
    return proc.stdout


def symbol_id(abs_path: str, container: str, signature: str, line: int) -> str:
    return f"{abs_path}::{container}::{signature}::L{line}"


def _function_base_name(signature: str) -> str:
    name = signature.split("(", 1)[0].strip()
    return name or signature


def _function_arity(signature: str) -> int:
    if "(" not in signature or ")" not in signature:
        return 0
    inside = signature.split("(", 1)[1].rsplit(")", 1)[0]
    if not inside:
        return 0
    return inside.count(":")


def _visibility_for_decl(source_lines: list[str], start_line: int) -> str:
    if start_line <= 0 or start_line > len(source_lines):
        return "internal"
    line = source_lines[start_line - 1]
    match = ACCESS_RE.search(line)
    if match:
        return match.group(1)
    return "internal"


def _infer_mutability(source_lines: list[str], line_no: int, name: str) -> bool:
    if line_no <= 0 or line_no > len(source_lines):
        return False
    line = source_lines[line_no - 1]
    return f"var {name}" in line


def _nearest_context(stack: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    for item in reversed(stack):
        if item["kind"] == kind:
            return item
    return None


def _extract_block(lines: list[str], start_index: int, marker: str) -> list[str]:
    line = lines[start_index]
    marker_pos = line.find(marker)
    if marker_pos < 0:
        return [line]

    block: list[str] = [line[marker_pos:]]
    balance = line[marker_pos:].count("(") - line[marker_pos:].count(")")
    idx = start_index + 1
    while balance > 0 and idx < len(lines):
        block.append(lines[idx])
        balance += lines[idx].count("(") - lines[idx].count(")")
        idx += 1
    return block


def _extract_call_target(block: list[str]) -> tuple[str | None, str | None, int]:
    joined = "\n".join(block)

    qualifier: str | None = None
    callee: str | None = None

    for idx, line in enumerate(block):
        dot_match = UNRESOLVED_DOT_RE.search(line)
        if not dot_match:
            continue
        if callee is None:
            callee = dot_match.group(1)
        for nxt in block[idx + 1 : idx + 8]:
            decl_match = UNRESOLVED_DECL_RE.search(nxt)
            if decl_match:
                candidate = decl_match.group(1)
                if candidate not in _CALL_IGNORE_NAMES:
                    qualifier = candidate
                    break
            if "argument_list" in nxt:
                break
        if callee is not None:
            break

    if callee is None:
        member_match = UNRESOLVED_MEMBER_RE.search(joined)
        if member_match:
            callee = member_match.group(1)

    if callee is None:
        declref_match = DECLREF_DECL_RE.search(joined)
        if declref_match:
            raw = declref_match.group(1)
            name = raw.rsplit(".", 1)[-1]
            if "(" in name:
                name = name.split("(", 1)[0]
            callee = name

    if callee is None:
        for candidate in UNRESOLVED_DECL_RE.findall(joined):
            if candidate in _CALL_IGNORE_NAMES:
                continue
            callee = candidate
            break

    arity = 0
    labels_match = LABELS_RE.search(joined)
    if labels_match:
        arity = labels_match.group(1).count(":")
    else:
        arity = len(re.findall(r"\(argument(?:\s|$)", joined))

    return qualifier, callee, arity


def _extract_call_line(block: list[str], default_line: int) -> int:
    joined = "\n".join(block)
    line_match = RANGE_LINE_RE.search(joined)
    if not line_match:
        return default_line
    return int(line_match.group(1))


def analyze_file(file_path: Path) -> dict[str, Any]:
    source_text = file_path.read_text(encoding="utf-8", errors="ignore")
    source_lines = source_text.splitlines()
    parse_text = run_dump_parse(file_path)
    parse_lines = parse_text.splitlines()

    abs_path = str(file_path.resolve())
    digest = hashlib.sha256(source_text.encode("utf-8", errors="ignore")).hexdigest()

    types: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    variables: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    mutations: list[dict[str, Any]] = []
    type_references: set[str] = set()

    depth = 0
    context_stack: list[dict[str, Any]] = []

    for idx, line in enumerate(parse_lines):
        while context_stack and depth <= context_stack[-1]["pop_depth"]:
            context_stack.pop()

        line_depth = depth

        type_match = TYPE_DECL_RE.search(line)
        if type_match:
            decl_kind, start_line_s, end_line_s, type_name = type_match.groups()
            start_line = int(start_line_s)
            end_line = int(end_line_s)
            owner = _nearest_context(context_stack, "type")
            container = owner["name"] if owner else "global"
            visibility = _visibility_for_decl(source_lines, start_line)
            sid = symbol_id(abs_path, container, type_name, start_line)
            record = {
                "id": sid,
                "name": type_name,
                "signature": type_name,
                "line": start_line,
                "end_line": end_line,
                "container": container,
                "decl_kind": decl_kind.replace("_decl", ""),
                "visibility": visibility,
                "kind": SYMBOL_KIND_TYPE,
                "file": abs_path,
            }
            types.append(record)
            if line.count("(") - line.count(")") > 0:
                context_stack.append(
                    {
                        "kind": "type",
                        "name": type_name,
                        "symbol_id": sid,
                        "pop_depth": line_depth,
                    }
                )

        func_match = FUNC_DECL_RE.search(line)
        if func_match:
            start_line = int(func_match.group(1))
            end_line = int(func_match.group(2))
            signature = func_match.group(3)
            owner = _nearest_context(context_stack, "type")
            container = owner["name"] if owner else "global"
            visibility = _visibility_for_decl(source_lines, start_line)
            sid = symbol_id(abs_path, container, signature, start_line)
            record = {
                "id": sid,
                "name": _function_base_name(signature),
                "signature": signature,
                "arity": _function_arity(signature),
                "line": start_line,
                "end_line": end_line,
                "container": container,
                "visibility": visibility,
                "kind": SYMBOL_KIND_FUNCTION,
                "file": abs_path,
            }
            functions.append(record)
            if line.count("(") - line.count(")") > 0:
                context_stack.append(
                    {
                        "kind": "function",
                        "name": signature,
                        "symbol_id": sid,
                        "pop_depth": line_depth,
                        "start_line": start_line,
                    }
                )

        var_match = VAR_DECL_RE.search(line)
        if var_match and " implicit " not in line:
            start_line = int(var_match.group(1))
            end_line = int(var_match.group(2))
            var_name = var_match.group(3)
            mutability = var_match.group(4)
            if not var_name.startswith("$"):
                owner_func = _nearest_context(context_stack, "function")
                owner_type = _nearest_context(context_stack, "type")
                container = "global"
                if owner_func:
                    container = owner_func["name"]
                elif owner_type:
                    container = owner_type["name"]
                visibility = _visibility_for_decl(source_lines, start_line)
                sid = symbol_id(abs_path, container, var_name, start_line)
                variables.append(
                    {
                        "id": sid,
                        "name": var_name,
                        "signature": var_name,
                        "line": start_line,
                        "end_line": end_line,
                        "container": container,
                        "visibility": visibility,
                        "is_mutable": (
                            mutability == "var"
                            if mutability in {"let", "var"}
                            else _infer_mutability(source_lines, start_line, var_name)
                        ),
                        "kind": SYMBOL_KIND_VARIABLE,
                        "file": abs_path,
                    }
                )

        if "(unresolved_decl_ref_expr" in line:
            for candidate in UNRESOLVED_DECL_RE.findall(line):
                if candidate and candidate[0].isupper():
                    type_references.add(candidate)

        function_ctx = _nearest_context(context_stack, "function")
        if function_ctx and "(call_expr" in line:
            block = _extract_block(parse_lines, idx, "(call_expr")
            qualifier, callee, arity = _extract_call_target(block)
            if callee:
                calls.append(
                    {
                        "source_symbol_id": function_ctx["symbol_id"],
                        "callee_name": callee,
                        "qualifier": qualifier,
                        "arity": arity,
                        "line": _extract_call_line(block, function_ctx["start_line"]),
                    }
                )

        if function_ctx and "(assign_expr" in line:
            window = "\n".join(parse_lines[max(0, idx - 8) : idx + 2])
            dot_targets = UNRESOLVED_DOT_RE.findall(window)
            decl_targets = UNRESOLVED_DECL_RE.findall(window)
            target_name = None
            target_kind = "unknown"
            if dot_targets:
                target_name = dot_targets[-1]
                target_kind = "property"
            elif decl_targets:
                for candidate in reversed(decl_targets):
                    if candidate in _CALL_IGNORE_NAMES:
                        continue
                    target_name = candidate
                    target_kind = "variable"
                    break
            if target_name:
                line_no = _extract_call_line(window.splitlines(), function_ctx["start_line"])
                mutations.append(
                    {
                        "source_symbol_id": function_ctx["symbol_id"],
                        "target_name": target_name,
                        "target_kind": target_kind,
                        "line": line_no,
                        "confidence": 0.8,
                    }
                )

        depth += line.count("(") - line.count(")")

    types.sort(key=lambda item: item["id"])
    functions.sort(key=lambda item: item["id"])
    variables.sort(key=lambda item: item["id"])
    calls.sort(
        key=lambda item: (
            item["source_symbol_id"],
            item["callee_name"],
            item["arity"],
            item["line"],
        )
    )
    mutations.sort(
        key=lambda item: (
            item["source_symbol_id"],
            item["target_name"],
            item["line"],
        )
    )

    return {
        "parser_version": PARSER_VERSION,
        "file": abs_path,
        "hash": digest,
        "types": types,
        "functions": functions,
        "variables": variables,
        "calls": calls,
        "mutations": mutations,
        "type_references": sorted(type_references),
    }
