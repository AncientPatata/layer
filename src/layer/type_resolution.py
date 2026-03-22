"""Advanced type coercion engine for layer.

Replaces the simple _coerce function in solidify.py with full support for
typing module generics: List[T], Dict[K, V], Tuple[T, ...], Union, Optional,
and Literal, as well as dataclasses and Pydantic v2 models.
"""
import dataclasses
import json
from typing import Any, Type, Union, get_args, get_origin

from .exceptions import CoercionError, StructureError

try:
    from typing import Literal
except ImportError:
    Literal = None  # Python < 3.8 fallback (not expected given 3.10 requirement)


def _parse_list_string(s: str) -> list:
    """Parse a string into a list via JSON or comma-separation."""
    stripped = s.strip()
    if stripped.startswith("["):
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            pass
    return [item.strip() for item in s.split(",") if item.strip()]


def _parse_dict_string(s: str) -> dict:
    """Parse a string into a dict via JSON or key=value pairs."""
    stripped = s.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            pass
    result = {}
    for pair in s.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def coerce(value: Any, type_hint: Type, parser=None) -> Any:
    """Coerce a value to the given type hint.

    Resolution order:
      1. Custom parser override
      2. None passthrough
      3. Generic type dispatch (Union, Literal, List, Dict, Tuple)
      4. Already-correct type (isinstance check)
      5. Dataclass: dict → dataclass(**dict)
      6. Pydantic v2: dict → Model.model_validate(dict)
      7. String-to-base-type conversions (bool, int, float, list, dict)
      8. Return value as-is for unrecognized types

    Raises:
        CoercionError: When coercion is attempted but definitively fails (e.g.
            int("abc"), or all Union candidates exhausted). Callers that want
            best-effort coercion should catch this.
        StructureError: When the value violates a structural constraint that
            should not be silently skipped (e.g. Literal mismatch).
    """
    # 1. Custom parser takes priority
    if parser is not None:
        return parser(value)

    # 2. None passthrough
    if value is None:
        return None

    # 3. Generic type dispatch
    origin = get_origin(type_hint)

    if origin is Union:
        args = get_args(type_hint)
        non_none_args = [a for a in args if a is not type(None)]
        for arg in non_none_args:
            try:
                return coerce(value, arg)
            except (CoercionError, ValueError, TypeError):
                continue
        raise CoercionError(
            f"Cannot coerce {value!r} to any type in {type_hint}: all candidates failed"
        )

    if Literal is not None and origin is Literal:
        allowed = get_args(type_hint)
        if value in allowed:
            return value
        raise StructureError(
            f"Value {value!r} is not one of the allowed Literal values: {allowed}"
        )

    if origin is list:
        args = get_args(type_hint)
        item_type = args[0] if args else None
        if isinstance(value, str):
            parsed = _parse_list_string(value)
        elif isinstance(value, list):
            parsed = value
        else:
            raise CoercionError(f"Cannot coerce {value!r} (type {type(value).__name__}) to list")
        if item_type is not None:
            return [coerce(item, item_type) for item in parsed]
        return parsed

    if origin is dict:
        args = get_args(type_hint)
        key_type = args[0] if len(args) > 0 else None
        val_type = args[1] if len(args) > 1 else None
        if isinstance(value, str):
            parsed = _parse_dict_string(value)
        elif isinstance(value, dict):
            parsed = value
        else:
            raise CoercionError(f"Cannot coerce {value!r} (type {type(value).__name__}) to dict")
        if key_type is not None or val_type is not None:
            return {
                (coerce(k, key_type) if key_type else k): (coerce(v, val_type) if val_type else v)
                for k, v in parsed.items()
            }
        return parsed

    if origin is tuple:
        args = get_args(type_hint)
        if isinstance(value, str):
            parsed = _parse_list_string(value)
        elif isinstance(value, (list, tuple)):
            parsed = list(value)
        else:
            raise CoercionError(f"Cannot coerce {value!r} (type {type(value).__name__}) to tuple")
        if args:
            # Tuple[T, ...] — variable-length homogeneous
            if len(args) == 2 and args[1] is Ellipsis:
                return tuple(coerce(item, args[0]) for item in parsed)
            # Fixed-length: coerce each position by its declared type
            return tuple(coerce(item, t) for item, t in zip(parsed, args))
        return tuple(parsed)

    # 4. Already the correct type
    try:
        if isinstance(value, type_hint):
            return value
    except TypeError:
        pass  # parameterized generics can't be used with isinstance

    # 5. Dataclass: accept a dict, instantiate with field values
    if dataclasses.is_dataclass(type_hint) and isinstance(value, dict):
        return type_hint(**value)

    # 6. Pydantic v2: delegate to model_validate
    if hasattr(type_hint, "model_validate") and isinstance(value, dict):
        return type_hint.model_validate(value)

    # 7. String-to-base-type conversions
    if isinstance(value, str):
        if type_hint is bool:
            return value.lower() in ("true", "1", "yes")
        if type_hint is int:
            try:
                return int(value)
            except (ValueError, TypeError) as e:
                raise CoercionError(f"Cannot coerce {value!r} to int") from e
        if type_hint is float:
            try:
                return float(value)
            except (ValueError, TypeError) as e:
                raise CoercionError(f"Cannot coerce {value!r} to float") from e
        if type_hint is list:
            return _parse_list_string(value)
        if type_hint is dict:
            return _parse_dict_string(value)

    # 8. Unknown type or non-string value with no matching conversion — return as-is
    return value
