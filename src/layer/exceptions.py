class ConfigError(Exception):
    """Base exception for all layer errors."""

    pass


class ValidationError(ConfigError):
    """One or more validation rules failed."""

    def __init__(self, field: str, message: str, rule: str, category: str):
        super().__init__(
            f"[Category: {category}] Field '{field}' failed rule '{rule}': {message}"
        )
        self.field = field
        self.message = message
        self.rule = rule
        self.category = category


class StructureError(ConfigError):
    """Source data doesn't match schema (unknown keys in strict mode)."""

    pass


class LayeringError(ConfigError):
    """Merge conflict or invalid rule application."""

    pass


class InterpolationError(ConfigError):
    """Raised on unresolvable or circular references."""

    pass


class InterpolationCycleError(InterpolationError):
    """Raised when a circular ${variable} reference is detected."""

    pass


class CoercionError(ConfigError):
    """Raised when a value cannot be coerced to the target type.

    Used internally so Union handling can try the next candidate type on failure.
    """

    pass


class MissingDependencyError(ConfigError):
    """Raised when an optional dependency (boto3, watchdog, etc.) is not installed."""

    pass


class HotReloadError(ConfigError):
    """Raised when an error occurs during hot-reload of configuration."""

    pass
