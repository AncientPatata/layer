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

    Follows a strict separation of concerns:

    1. **Load** — ``load()`` ingests all providers, merges overlays (with optional
       ``LayerRule`` per provider), resolves ``${variable}`` references, and freezes
       the live config. It never runs validation.
    2. **Validate** — call ``pipeline.validate(categories)`` explicitly after loading.
    3. **Hot-reload** — providers with ``watch=True`` trigger ``_reload()`` automatically
       when their source changes.

    Example:
        pipeline = (
            ConfigPipeline(AppConfig, mode=SolidifyMode.STRICT)
            .add_provider(FileProvider("base.yml"))
            .add_provider(EnvProvider("APP"), rules={"ports": LayerRule.APPEND})
        )
        config = pipeline.load()
        pipeline.validate(["server"]).raise_if_invalid()
    """

    def __init__(
        self,
        target: Any,
        mode=None,
        observer=None,
        logger: logging.Logger = None,
    ):
        """Initialize the pipeline.

        Args:
            target: A ``@layerclass`` class or instance. If a class is given,
                a fresh instance is created as the live config.
            mode: Optional ``SolidifyMode`` applied to all ``solidify()`` calls
                inside ``load()`` and ``_build_shadow()``. Defaults to ``None``
                (legacy LAX-like behavior).
            observer: Optional ``BasePipelineObserver`` instance for lifecycle
                hooks. If ``None`` and ``logger`` is also ``None``, no events
                are emitted.
            logger: Optional ``logging.Logger``. When provided, a
                ``LoggerObserver`` is automatically created and used.
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

        if logger is not None:
            from .observers import LoggerObserver

            self._observer = LoggerObserver(logger)
        else:
            self._observer = observer  # May be None or a BasePipelineObserver

    @property
    def config(self) -> Any:
        """The live config instance."""
        return self._live

    def add_provider(self, provider, rules: dict = None) -> "ConfigPipeline":
        """Add a provider to the pipeline, optionally with per-field layering rules.

        Providers are applied in order during ``load()``. Later providers override
        values from earlier ones, subject to any ``LayerRule`` overrides.

        Args:
            provider: A ``BaseProvider`` instance (``FileProvider``, ``EnvProvider``,
                ``SSMProvider``, etc.).
            rules: Optional ``{field_name: LayerRule}`` dict controlling how each
                field from this provider is merged. Supports dot-notation for nested
                fields (e.g. ``{"database.ports": LayerRule.APPEND}``). Fields not
                listed use ``LayerRule.OVERRIDE`` (default).

        Returns:
            ``self`` for fluent chaining.

        Example:
            pipeline.add_provider(EnvProvider("APP"), rules={"ports": LayerRule.APPEND})
        """
        self._providers.append((provider, rules or {}))
        return self

    def on_change(self, field_path: str, callback: Callable) -> "ConfigPipeline":
        """Register a callback for field changes during hot-reload.

        Args:
            field_path: Dot-separated field path (e.g. ``"database.host"``),
                or ``"*"`` to override the default mutator for all changes.
            callback: Called with ``(field, old_value, new_value, shadow_config)``.

        Returns:
            ``self`` for fluent chaining.
        """
        if field_path == "*":
            self._mutator = callback
        else:
            self._reactors.setdefault(field_path, []).append(callback)
        return self

    def load(self) -> Any:
        """Execute all providers in order, merging results onto the live config.

        The pipeline performs four operations in sequence:

        1. Read each provider and coerce its data via ``solidify()``.
        2. Layer each overlay onto the live config using the provider's rules.
        3. Resolve all ``${variable}`` interpolations.
        4. Freeze the live config to prevent accidental mutation.

        No validation is performed. Call ``pipeline.validate()`` separately.

        Returns:
            The frozen live config instance.
        """
        from .solidify import solidify

        for provider, rules in self._providers:
            data = provider.read()
            if self._observer:
                self._observer.on_provider_read(provider.source_name, data)
            if not data:
                continue
            overlay = solidify(data, self._target_cls, source=provider.source_name, mode=self._mode)
            self._live.layer(overlay, rules=rules)
            if self._observer:
                self._observer.on_layer_merged(provider.source_name, rules)

        self._live.resolve()
        self._live.freeze()
        self._loaded = True
        return self._live

    def validate(self, categories=None):
        """Run validation on the live config.

        This is the correct place to trigger validation — never inside ``load()``.

        Args:
            categories: Passed directly to ``config.validate(categories)``.
                ``None`` runs bare (uncategorized) rules only; ``"*"`` or
                ``["*"]`` runs all categories.

        Returns:
            A ``ValidationResult`` with ``.errors`` and ``.raise_if_invalid()``.
        """
        return self._live.validate(categories)

    def _build_shadow(self) -> Any:
        """Build a fresh config by re-running all providers.

        Does not touch the live config. Used internally by ``_reload()``.
        """
        from .solidify import solidify

        shadow = self._target_cls()
        for provider, rules in self._providers:
            data = provider.read()
            if not data:
                continue
            overlay = solidify(data, self._target_cls, source=provider.source_name, mode=self._mode)
            shadow.layer(overlay, rules=rules)
        shadow.resolve()
        shadow.freeze()
        return shadow

    def _reload(self):
        """Hot-reload: build shadow, diff, filter locked fields, fire reactors, apply mutator."""
        shadow = self._build_shadow()
        diffs = self._live.diff(shadow, redact=False)
        if not diffs:
            return

        if self._observer:
            self._observer.on_hot_reload_triggered(diffs)

        # Filter out non-reloadable fields
        filtered = []
        for d in diffs:
            fdef = _get_fdef_by_path(self._target_cls, d["field"])
            if fdef is not None and not fdef.reloadable:
                logging.warning("layer: Skipped hot-reload for locked field '%s'", d["field"])
                if self._observer:
                    self._observer.on_hot_reload_locked(d["field"])
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

        Requires watchdog: ``pip install layer[watch]``
        """
        watchable = [p for p, _ in self._providers if p.watchable]
        if not watchable:
            return self

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            from .exceptions import MissingDependencyError

            raise MissingDependencyError(
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
