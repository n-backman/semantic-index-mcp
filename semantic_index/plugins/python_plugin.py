from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from ..plugin_api import LanguagePlugin, ParsedFile


class _SymbolVisitor(ast.NodeVisitor):
    """Walk a Python AST and collect symbols and call edges."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.symbols: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self._scope_stack: list[str] = []

    def _current_scope(self) -> str | None:
        return self._scope_stack[-1] if self._scope_stack else None

    def _sym_id(self, name: str, line: int) -> str:
        return f"{self.file_path}::{name}:{line}"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        sym_id = self._sym_id(node.name, node.lineno)
        self.symbols.append({
            "id": sym_id,
            "name": node.name,
            "kind": "type",
            "file": self.file_path,
            "line": node.lineno,
            "container": self._current_scope(),
        })
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        sym_id = self._sym_id(node.name, node.lineno)
        args = node.args
        all_args = args.posonlyargs + args.args + args.kwonlyargs
        arity = len(all_args)
        arg_names = [a.arg for a in all_args]
        self.symbols.append({
            "id": sym_id,
            "name": node.name,
            "kind": "function",
            "file": self.file_path,
            "line": node.lineno,
            "arity": arity,
            "signature": f"{node.name}({', '.join(arg_names)})",
            "container": self._current_scope(),
        })
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.edges.append({
                "kind": "import",
                "src_file": self.file_path,
                "dst_module": alias.name,
                "line": node.lineno,
            })

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.edges.append({
                "kind": "import",
                "src_file": self.file_path,
                "dst_module": node.module,
                "line": node.lineno,
            })


class PythonPlugin(LanguagePlugin):
    language = "python"
    extensions = frozenset({".py"})

    def parse_file(self, path: Path) -> ParsedFile:
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            return ParsedFile(symbols=[], edges=[])

        visitor = _SymbolVisitor(str(path))
        visitor.visit(tree)
        return ParsedFile(symbols=visitor.symbols, edges=visitor.edges)

    def classify_file(self, rel_path: str, parsed: ParsedFile) -> str | None:
        lower = rel_path.replace("\\", "/").lower()
        if "test" in lower or "spec" in lower:
            return "Auditor"
        if any(
            lower.endswith(suffix)
            for suffix in ("/config.py", "/settings.py", "/constants.py")
        ):
            return "Law"
        return None
