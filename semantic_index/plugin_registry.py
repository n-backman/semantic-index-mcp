from __future__ import annotations

import warnings

from .plugin_api import LanguagePlugin


class PluginRegistry:
    def __init__(self) -> None:
        self._by_ext: dict[str, LanguagePlugin] = {}
        self._load_builtins()
        self._load_entry_points()

    def _load_builtins(self) -> None:
        from .plugins.swift_plugin import SwiftPlugin
        from .plugins.python_plugin import PythonPlugin
        from .plugins.typescript_plugin import TypeScriptPlugin

        for plugin_cls in (SwiftPlugin, PythonPlugin, TypeScriptPlugin):
            plugin = plugin_cls()
            for ext in plugin.extensions:
                self._by_ext[ext] = plugin

    def _load_entry_points(self) -> None:
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group="semantic_index.plugins")
        except Exception:
            return
        for ep in eps:
            try:
                plugin_cls = ep.load()
                plugin = plugin_cls()
                for ext in plugin.extensions:
                    self._by_ext[ext] = plugin
            except Exception as exc:
                warnings.warn(
                    f"Failed to load semantic_index plugin {ep.name!r}: {exc}",
                    stacklevel=2,
                )

    def get(self, ext: str) -> LanguagePlugin | None:
        return self._by_ext.get(ext.lower())

    def all_extensions(self) -> frozenset[str]:
        return frozenset(self._by_ext.keys())

    def all_plugins(self) -> list[LanguagePlugin]:
        seen: set[int] = set()
        plugins: list[LanguagePlugin] = []
        for plugin in self._by_ext.values():
            if id(plugin) not in seen:
                seen.add(id(plugin))
                plugins.append(plugin)
        return plugins
