"""Pipeline observer interface and built-in implementations.

Observers provide deep, programmatic visibility into the pipeline lifecycle
without hardcoding logging statements into the core engine. Subclass
``BasePipelineObserver`` to integrate with metrics systems (Datadog, Prometheus,
etc.) or implement custom alerting logic.
"""

import logging
from typing import Any


class BasePipelineObserver:
    """Abstract base class for pipeline lifecycle observers.

    All methods are no-ops by default. Subclass and override only the hooks
    you need.

    Example:
        class MetricsObserver(BasePipelineObserver):
            def on_hot_reload_triggered(self, diffs):
                statsd.increment("config.reload", tags=[f"changes:{len(diffs)}"])

            def on_hot_reload_locked(self, field):
                statsd.increment("config.reload.locked", tags=[f"field:{field}"])
    """

    def on_provider_read(self, provider_name: str, data: dict) -> None:
        """Called after a provider successfully reads its data.

        Args:
            provider_name: The ``source_name`` of the provider.
            data: The raw dict returned by the provider.
        """

    def on_coercion_error(
        self, field: str, value: Any, target_type: type, error: Exception
    ) -> None:
        """Called when a type coercion fails (LAX mode swallows the error).

        Args:
            field: The field name that failed coercion.
            value: The raw value that could not be coerced.
            target_type: The target type that coercion was attempted for.
            error: The original exception.
        """

    def on_layer_merged(self, provider_name: str, rules_applied: dict) -> None:
        """Called after each provider's overlay is layered onto the live config.

        Args:
            provider_name: The ``source_name`` of the provider.
            rules_applied: The ``LayerRule`` dict used during the merge.
        """

    def on_hot_reload_triggered(self, diffs: list) -> None:
        """Called when a hot-reload detects one or more field changes.

        Args:
            diffs: List of diff dicts (field, old_value, new_value, …) from
                ``config.diff(shadow)``.
        """

    def on_hot_reload_locked(self, field: str) -> None:
        """Called when a hot-reload is skipped for a ``reloadable=False`` field.

        Args:
            field: Dot-notation path of the locked field.
        """


class LoggerObserver(BasePipelineObserver):
    """Observer that emits structured log messages via a standard ``logging.Logger``.

    Args:
        logger: A ``logging.Logger`` instance. Typically obtained via
            ``logging.getLogger(__name__)``.

    Example:
        import logging
        pipeline = ConfigPipeline(AppConfig, logger=logging.getLogger("myapp"))
    """

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def on_provider_read(self, provider_name: str, data: dict) -> None:
        self._logger.debug("layer: provider '%s' read %d key(s)", provider_name, len(data))

    def on_coercion_error(
        self, field: str, value: Any, target_type: type, error: Exception
    ) -> None:
        self._logger.warning(
            "layer: coercion failed for field '%s' (value=%r, target=%s): %s",
            field,
            value,
            getattr(target_type, "__name__", str(target_type)),
            error,
        )

    def on_layer_merged(self, provider_name: str, rules_applied: dict) -> None:
        self._logger.debug(
            "layer: merged overlay from '%s' (rules=%s)", provider_name, rules_applied
        )

    def on_hot_reload_triggered(self, diffs: list) -> None:
        fields = [d["field"] for d in diffs]
        self._logger.info("layer: hot-reload detected %d change(s): %s", len(diffs), fields)

    def on_hot_reload_locked(self, field: str) -> None:
        self._logger.warning(
            "layer: skipped hot-reload for locked field '%s' (reloadable=False)", field
        )
