"""
Variable interpolation engine for layerconfig.

Resolves ${field_name} references within string values, with cycle detection.
"""

import re
from typing import Any

from .exceptions import InterpolationCycleError, InterpolationError

_VAR_PATTERN = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def resolve_value(value: Any, config, _resolving: set[str] = None) -> Any:
    """Resolve ${...} references in a single value.

    Supports:
      - Simple: ${host}
      - Nested (dot-path): ${database.host}
      - Mixed: "http://${host}:${port}/api"

    Raises InterpolationError on circular references.
    """
    if not isinstance(value, str):
        return value

    if _resolving is None:
        _resolving = set()

    def _replace(match):
        ref = match.group(1)

        if ref in _resolving:
            raise InterpolationCycleError(
                f"Circular reference detected: {ref} -> {' -> '.join(_resolving)}"
            )

        _resolving.add(ref)
        try:
            resolved = _get_dotted(config, ref)
            if resolved is None:
                raise InterpolationError(f"Unresolvable reference: ${{{ref}}}")
            # Recursively resolve (the target value may itself contain ${...})
            resolved = resolve_value(resolved, config, _resolving)
        finally:
            _resolving.discard(ref)

        return str(resolved)

    return _VAR_PATTERN.sub(_replace, value)


def _get_dotted(config, dotted_key: str) -> Any:
    """Traverse a dotted path like 'database.host' on a config object."""
    parts = dotted_key.split(".")
    obj = config
    for part in parts:
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def resolve_all(config) -> None:
    """Resolve all ${...} references in a config object, in-place.

    Call this after all layers have been merged and before freeze()/validate().
    """
    for name, fdef in config._field_defs.items():
        val = getattr(config, name)

        # Recurse into nested @layer_obj
        if hasattr(fdef.type_hint, "_field_defs") and hasattr(val, "_field_defs"):
            resolve_all(val)
            continue

        if isinstance(val, str) and "${" in val:
            try:
                resolved = resolve_value(val, config)
                setattr(config, name, resolved)
                # Push to source history
                config._sources[name].push("interpolation", resolved)
            except InterpolationError:
                pass  # Leave as-is if unresolvable (or raise, depending on preference)

        elif isinstance(val, list):
            setattr(
                config,
                name,
                [resolve_value(item, config) if isinstance(item, str) else item for item in val],
            )

        elif isinstance(val, dict):
            setattr(
                config,
                name,
                {k: resolve_value(v, config) if isinstance(v, str) else v for k, v in val.items()},
            )
