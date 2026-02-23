# semantic-index-mcp

## Writing a New Language Plugin

Plugins live in `semantic_index/plugins/`. Each plugin is a class that subclasses `LanguagePlugin` from `plugin_api.py`.

### Minimal skeleton

```python
from pathlib import Path
from ..plugin_api import LanguagePlugin, ParsedFile

class MyLangPlugin(LanguagePlugin):
    language = "mylang"
    extensions = frozenset({".ml"})          # file extensions this plugin handles

    def parse_file(self, path: Path) -> ParsedFile:
        """REQUIRED. Return symbols and edges extracted from the file."""
        symbols = []   # list of symbol dicts — see schema below
        edges = []     # list of edge dicts — see schema below
        return ParsedFile(symbols=symbols, edges=edges)

    def classify_file(self, rel_path: str, parsed: ParsedFile) -> str | None:
        """OPTIONAL. Return a role string or None."""
        # Built-in roles: "View", "Law", "Auditor", "Citizen"
        if "test" in rel_path.lower():
            return "Auditor"
        return None

    def score_symbol(self, symbol: dict, base_score: float) -> float:
        """OPTIONAL. Adjust impact score. Default is pass-through."""
        return base_score
```

### Symbol dict fields

| Field | Required | Notes |
|-|-|-|
| `id` | yes | Unique string. Convention: `"{abs_path}::{container}::{name}::{line}"` |
| `name` | yes | Unqualified symbol name |
| `kind` | yes | `"type"`, `"function"`, or `"variable"` |
| `file` | yes | Absolute path string |
| `line` | yes | 1-based start line |
| `signature` | no | Full signature string |
| `container` | no | Enclosing type or function name, `"global"` if top-level |
| `visibility` | no | `"public"`, `"internal"`, `"private"`, etc. |
| `arity` | no | Parameter count (functions only) |

### Edge dict fields

`kind: "call"` — function calls:
```python
{"kind": "call", "source_symbol_id": sid, "callee_name": "foo", "qualifier": None, "arity": 1, "line": 42}
```

`kind: "mutation"` — variable writes:
```python
{"kind": "mutation", "source_symbol_id": sid, "target_name": "myVar", "target_kind": "property", "line": 10, "confidence": 0.9}
```

### Registering a built-in plugin

Add an entry to `pyproject.toml`:
```toml
[project.entry-points."semantic_index.plugins"]
mylang = "semantic_index.plugins.my_lang_plugin:MyLangPlugin"
```

Built-ins are also imported directly in `plugin_registry.py:_load_builtins()`. Third-party plugins only need the entry-point — they're auto-discovered at startup.

### Notes
- `parse_file` must not raise on malformed input; return empty `ParsedFile` instead.
- The cache key is the file's SHA-256 hash. If `parse_file` is deterministic, cached results are reused automatically.
- `extensions` values must be lowercase with the leading dot (e.g. `".go"`).
