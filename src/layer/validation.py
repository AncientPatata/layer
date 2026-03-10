import os
from dataclasses import dataclass
from typing import List, Any
from .exceptions import ConfigError, ValidationError


@dataclass
class ValidationResult:
    errors: List[ValidationError]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def raise_if_invalid(self):
        if not self.is_valid:
            # Raise the first one, or a bundled error. We'll raise a summary for now.
            summary = "\n".join([str(e) for e in self.errors])
            raise ConfigError(f"Configuration validation failed:\n{summary}")

    def summary(self) -> str:
        if self.is_valid:
            return "Configuration is valid."
        return "\n".join([str(e) for e in self.errors])


# --- Built-in Validators ---


def require(value: Any, field_name: str, config: Any) -> True:
    """Field must be set (not None)."""
    if value is None:
        raise ValidationError(field_name, "Field is required", "require", "unknown")
    return True


def one_of(*allowed_values):
    """Value must be in the given set."""

    def _one_of(value: Any, field_name: str, config: Any):
        if value is not None and value not in allowed_values:
            raise ValidationError(
                field_name, f"Must be one of {allowed_values}", "one_of", "unknown"
            )
        return True

    return _one_of


def path_exists(value: Any, field_name: str, config: Any):
    """Path must exist on filesystem."""
    if value is not None and not os.path.exists(str(value)):
        raise ValidationError(
            field_name, f"Path '{value}' does not exist", "path_exists", "unknown"
        )
    return True


def optional(value, field_name, config):
    """Explicitly marks field as optional. Always passes. Documentation-only."""
    return True


def in_range(lo, hi):
    """Numeric value must be in [lo, hi]."""

    def _in_range(value, field_name, config):
        if value is not None and not (lo <= value <= hi):
            raise ValidationError(
                field_name,
                f"Must be between {lo} and {hi}, got {value}",
                "in_range",
                "unknown",
            )
        return True

    return _in_range


def instance_of(expected_type):
    """Value must be isinstance(val, expected_type)."""

    def _instance_of(value: Any, field_name: str, config: Any):
        if value is not None and not isinstance(value, expected_type):
            raise ValidationError(
                field_name,
                f"Expected {expected_type.__name__}, got {type(value).__name__}",
                "instance_of",
                "unknown",
            )
        return True

    return _instance_of


def min_length(n):
    """String length >= n."""

    def _min_length(value: Any, field_name: str, config: Any):
        if value is not None and len(str(value)) < n:
            raise ValidationError(
                field_name,
                f"Length must be >= {n}, got {len(str(value))}",
                "min_length",
                "unknown",
            )
        return True

    return _min_length


def requires_if(trigger_field: str, trigger_value: Any):
    """Field is required when another field equals a specific value.

    Usage:
        client_cert: str = field(str,
            cluster=[requires_if("tls_enabled", True)],
            default=None
        )
    """

    def _requires_if(value, field_name, config):
        trigger_val = getattr(config, trigger_field, None)
        if trigger_val == trigger_value and value is None:
            raise ValidationError(
                field_name,
                f"Required when '{trigger_field}' is {trigger_value!r}",
                "requires_if",
                "unknown",
            )
        return True

    _requires_if.__name__ = "requires_if"
    return _requires_if


def requires_any(*field_names):
    """At least one of the listed fields must be set (not None).

    Apply this validator to any ONE of the fields in the group.

    Usage:
        token: str = field(str, auth=[requires_any("token", "username")], default=None)
        username: str = field(str, default=None)
    """

    def _requires_any(value, field_name, config):
        if all(getattr(config, f, None) is None for f in field_names):
            raise ValidationError(
                field_name,
                f"At least one of {field_names} must be set",
                "requires_any",
                "unknown",
            )
        return True

    _requires_any.__name__ = "requires_any"
    return _requires_any


def requires_all(*field_names):
    """All of the listed fields must be set together, or none of them.

    Usage:
        client_cert: str = field(str,
            cluster=[requires_all("client_certificate", "client_key")],
            default=None
        )
    """

    def _requires_all(value, field_name, config):
        values = [getattr(config, f, None) for f in field_names]
        set_count = sum(1 for v in values if v is not None)
        if 0 < set_count < len(field_names):
            missing = [f for f, v in zip(field_names, values) if v is None]
            raise ValidationError(
                field_name,
                f"Fields {field_names} must all be set together. Missing: {missing}",
                "requires_all",
                "unknown",
            )
        return True

    _requires_all.__name__ = "requires_all"
    return _requires_all


def mutually_exclusive(*field_names):
    """At most one of the listed fields may be set.

    Usage:
        token: str = field(str,
            auth=[mutually_exclusive("token", "username_password", "certificate")],
            default=None
        )
    """

    def _mutually_exclusive(value, field_name, config):
        set_fields = [f for f in field_names if getattr(config, f, None) is not None]
        if len(set_fields) > 1:
            raise ValidationError(
                field_name,
                f"Only one of {field_names} may be set, but got: {set_fields}",
                "mutually_exclusive",
                "unknown",
            )
        return True

    _mutually_exclusive.__name__ = "mutually_exclusive"
    return _mutually_exclusive


def depends_on(*required_fields):
    """If this field is set, the listed fields must also be set.

    Usage:
        client_key: str = field(str,
            cluster=[depends_on("client_certificate")],
            default=None
        )
    """

    def _depends_on(value, field_name, config):
        if value is not None:
            missing = [f for f in required_fields if getattr(config, f, None) is None]
            if missing:
                raise ValidationError(
                    field_name,
                    f"When '{field_name}' is set, {required_fields} must also be set. Missing: {missing}",
                    "depends_on",
                    "unknown",
                )
        return True

    _depends_on.__name__ = "depends_on"
    return _depends_on


def regex(pattern: str, message: str = None):
    """String must match the given regex pattern.

    Usage:
        endpoint: str = field(str, cluster=[regex(r"https?://.+")])
    """
    import re as _re

    compiled = _re.compile(pattern)

    def _regex(value, field_name, config):
        if value is not None and not compiled.match(str(value)):
            msg = message or f"Must match pattern: {pattern}"
            raise ValidationError(field_name, msg, "regex", "unknown")
        return True

    _regex.__name__ = "regex"
    return _regex


def max_length(n: int):
    """String length <= n."""

    def _max_length(value, field_name, config):
        if value is not None and len(str(value)) > n:
            raise ValidationError(
                field_name,
                f"Length must be <= {n}, got {len(str(value))}",
                "max_length",
                "unknown",
            )
        return True

    _max_length.__name__ = "max_length"
    return _max_length


def not_empty(value, field_name, config):
    """Value must not be empty (empty string, empty list, empty dict).

    Unlike `require` (which checks for None), this catches "" and [] too.
    """
    if value is not None:
        if isinstance(value, (str, list, dict)) and len(value) == 0:
            raise ValidationError(
                field_name,
                "Must not be empty",
                "not_empty",
                "unknown",
            )
    return True


def is_url(value, field_name, config):
    """Value must look like a URL (http:// or https://)."""
    if value is not None:
        if not isinstance(value, str) or not value.startswith(("http://", "https://")):
            raise ValidationError(
                field_name,
                f"Must be a valid URL (http/https), got: {value!r}",
                "is_url",
                "unknown",
            )
    return True


def is_positive(value, field_name, config):
    """Numeric value must be > 0."""
    if value is not None:
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValidationError(
                field_name,
                f"Must be positive, got {value}",
                "is_positive",
                "unknown",
            )
    return True


def is_port(value, field_name, config):
    """Shorthand for in_range(1, 65535) with a clearer error message."""
    if value is not None:
        if not isinstance(value, int) or not (1 <= value <= 65535):
            raise ValidationError(
                field_name,
                f"Must be a valid port (1-65535), got {value}",
                "is_port",
                "unknown",
            )
    return True


def each_item(validator):
    """Apply a validator to each item in a list field.

    Usage:
        partition_ids: list = field(list, each_item(min_length(1)), default=[])
    """

    def _each_item(value, field_name, config):
        if value is not None and isinstance(value, list):
            for i, item in enumerate(value):
                try:
                    validator(item, f"{field_name}[{i}]", config)
                except ValidationError as e:
                    raise ValidationError(
                        f"{field_name}[{i}]",
                        e.message,
                        f"each_item({getattr(validator, '__name__', 'custom')})",
                        "unknown",
                    )
        return True

    _each_item.__name__ = "each_item"
    return _each_item
