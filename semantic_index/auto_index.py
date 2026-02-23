from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from .graph_store import graph_path
from .indexer import BuildStats, SemanticIndexer, discover_files, normalize_roots
from .plugin_registry import PluginRegistry


class AutoIndexManager:
    def __init__(
        self,
        repo_root: Path,
        roots: list[Path] | None = None,
        watch: bool = False,
        watch_interval: float = 2.0,
        on_refresh: Callable[[BuildStats], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.roots = normalize_roots(self.repo_root, roots)
        self.watch = watch
        self.watch_interval = max(0.2, float(watch_interval))
        self.on_refresh = on_refresh
        self.on_error = on_error
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_snapshot: tuple[tuple[str, int, int], ...] | None = None
        self.last_error: str | None = None
        self.last_stats: BuildStats | None = None

    def start(self, bootstrap: bool = False) -> None:
        self._stop_event.clear()
        if bootstrap:
            self.refresh(force=not graph_path(self.repo_root).exists())
        else:
            self._last_snapshot = self._repo_snapshot()

        if self.watch and self._thread is None:
            self._thread = threading.Thread(
                target=self._watch_loop,
                name="semantic-index-watch",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self.watch_interval * 2, 1.0))
            self._thread = None

    def wait_forever(self) -> None:
        while not self._stop_event.wait(3600):
            time.sleep(0)

    def refresh_if_needed(self) -> bool:
        with self._lock:
            snapshot = self._repo_snapshot()
            graph_exists = graph_path(self.repo_root).exists()
            if graph_exists and snapshot == self._last_snapshot:
                return False
            force = not graph_exists
        return self.refresh(force=force)

    def refresh(self, force: bool = False) -> bool:
        with self._lock:
            indexer = SemanticIndexer(self.repo_root, self.roots[1:])
            graph_exists = graph_path(self.repo_root).exists()
            try:
                if force or not graph_exists:
                    _, stats = indexer.build_full()
                else:
                    _, stats = indexer.build_incremental()
            except Exception as exc:
                self.last_error = str(exc)
                if self.on_error is not None:
                    self.on_error(self.last_error)
                if force or not graph_exists:
                    raise
                return False

            self.last_error = None
            self.last_stats = stats
            self._last_snapshot = self._repo_snapshot()
            if self.on_refresh is not None:
                self.on_refresh(stats)
            return True

    def _watch_loop(self) -> None:
        while not self._stop_event.wait(self.watch_interval):
            try:
                self.refresh_if_needed()
            except Exception as exc:
                self.last_error = str(exc)
                if self.on_error is not None:
                    self.on_error(self.last_error)

    def _repo_snapshot(self) -> tuple[tuple[str, int, int], ...]:
        registry = PluginRegistry()
        snapshot: list[tuple[str, int, int]] = []
        for rel_path, abs_path in discover_files(self.repo_root, self.roots[1:], registry):
            try:
                stat = abs_path.stat()
            except FileNotFoundError:
                continue
            snapshot.append((rel_path, stat.st_mtime_ns, stat.st_size))
        snapshot.sort()
        return tuple(snapshot)
