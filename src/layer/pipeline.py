"""ConfigPipeline — fluent orchestrator for multi-source config loading and hot-reloading."""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional


def _get_fdef_by_path(target_cls, dot_path: str):
    """Traverse nested _field_defs to find the FieldDef at a dot-notation path.

    Returns None if any segment of the path is not found.
    """
    parts = dot_path.split(".")
    cls = target_cls
    fdef = None
    for part in parts:
        if not hasattr(cls, "_field_defs"):
            return None
        fdef = cls._field_defs.get(part)
        if fdef is None:
            return None
        cls = fdef.type_hint
    return fdef


class ConfigPipeline:
    """Orchestrates multiple providers into a layered config instance.

    Supports fluent chaining, hot-reload with diff-based callbacks,
    and thread-safe mutation.

    Usage:
        pipeline = (
            ConfigPipeline(AppConfig)
            .add_provider(FileProvider("config.yml", watch=True))
            .add_provider(EnvProvider(prefix="APP"))
        )
        config = pipeline.load()
    """

    def __init__(self, target: Any, mode=None):
        """Initialize the pipeline.

        Args:
            target: A @layer_obj class or instance. If a class is given,
                a fresh instance is created as the live config.
            mode: Optional SolidifyMode applied to all solidify() calls inside
                load() and _build_shadow(). Defaults to None (legacy behavior).
        """
        if isinstance(target, type):
            self._target_cls = target
            self._live = target()
        else:
            self._target_cls = type(target)
            self._live = target

        self._mode = mode
        self._providers: List = []
        self._reactors: Dict[str, List[Callable]] = {}
        self._mutator: Optional[Callable] = None
        self._lock = threading.Lock()
        self._watcher = None
        self._loaded = False

    @property
    def config(self) -> Any:
        """The live config instance."""
        return self._live

    def add_provider(self, provider) -> "ConfigPipeline":
        """Add a provider to the pipeline. Returns self for chaining.

        Providers are applied in order during load(). Later providers
        override values from earlier ones.
        """
        self._providers.append(provider)
        return self

    def on_change(self, field_path: str, callback: Callable) -> "ConfigPipeline":
        """Register a callback for field changes during hot-reload.

        Args:
            field_path: Dot-separated field path (e.g. "database.host"),
                or "*" to override the default mutator.
            callback: Called with (field, old_value, new_value, shadow_config).

        Returns self for chaining.
        """
        if field_path == "*":
            self._mutator = callback
        else:
            self._reactors.setdefault(field_path, []).append(callback)
        return self

    def load(self) -> Any:
        """Execute all providers in order, layering results onto the live config.

        Freezes the config after loading. Returns the live config instance.
        """
        from .solidify import solidify

        for provider in self._providers:
            data = provider.read()
            if not data:
                continue
            overlay = solidify(
                data, self._target_cls, source=provider.source_name, mode=self._mode
            )
            self._live.layer(overlay)

        self._live.freeze()
        self._loaded = True
        return self._live

    def _build_shadow(self) -> Any:
        """Build a fresh config by re-running all providers.

        Does not touch the live config. Used internally by _reload().
        """
        from .solidify import solidify

        shadow = self._target_cls()
        for provider in self._providers:
            data = provider.read()
            if not data:
                continue
            overlay = solidify(
                data, self._target_cls, source=provider.source_name, mode=self._mode
            )
            shadow.layer(overlay)
        shadow.freeze()
        return shadow

    def _reload(self):
        """Hot-reload: build shadow, diff, fire reactors, apply mutator."""
        shadow = self._build_shadow()
        diffs = self._live.diff(shadow, redact=False)
        if not diffs:
            return

        # Filter out non-reloadable fields
        filtered = []
        for d in diffs:
            fdef = _get_fdef_by_path(self._target_cls, d["field"])
            if fdef is not None and not fdef.reloadable:
                logging.warning(
                    "layer: Skipped hot-reload for locked field '%s'", d["field"]
                )
                continue
            filtered.append(d)
        diffs = filtered

        if not diffs:
            return

        # Phase 1: Fire specific reactors
        for d in diffs:
            field_path = d["field"]
            for callback in self._reactors.get(field_path, []):
                callback(field_path, d["old_value"], d["new_value"], shadow)

        # Phase 2: Apply mutation
        if self._mutator:
            for d in diffs:
                self._mutator(d["field"], d["old_value"], d["new_value"], shadow)
        else:
            self._default_mutator(diffs, shadow)

    def _default_mutator(self, diffs, shadow):
        """Thread-safe default mutator: unfreeze, apply all diffs, freeze."""
        with self._lock:
            self._live._unfreeze_deep()
            for d in diffs:
                self._live.set(d["field"], d["new_value"], source="hot-reload")
            self._live.freeze()

    def start(self):
        """Start watching for changes from watchable providers.

        Requires watchdog: pip install layer[watch]
        """
        watchable = [p for p in self._providers if p.watchable]
        if not watchable:
            return self

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            raise ImportError(
                "watchdog is required for hot-reloading: pip install layer[watch]"
            )

        pipeline = self

        class _ReloadHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if not event.is_directory:
                    pipeline._reload()

        self._watcher = Observer()
        for provider in watchable:
            import os

            watch_dir = os.path.dirname(os.path.abspath(provider._path))
            self._watcher.schedule(_ReloadHandler(), watch_dir, recursive=False)
        self._watcher.daemon = True
        self._watcher.start()
        return self

    def stop(self):
        """Stop the file watcher."""
        if self._watcher:
            self._watcher.stop()
            self._watcher.join()
            self._watcher = None
