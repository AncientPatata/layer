import os
from typing import Type, Dict, Any, Optional, List
from .exceptions import StructureError


def _is_layer_obj_type(cls):
    """Check if a type is a @layer_obj decorated class."""
    return (
        isinstance(cls, type)
        and hasattr(cls, "_field_defs")
        and hasattr(cls, "_is_layer_obj_marker")
    )


def _coerce(value, type_hint, parser=None):
    # Custom parser takes priority
    if parser is not None:
        return parser(value)

    if isinstance(value, type_hint):
        return value

    if value is None:
        return value

    if isinstance(value, str):
        if type_hint is bool:
            return value.lower() in ("true", "1", "yes")
        if type_hint is int:
            return int(value)
        if type_hint is float:
            return float(value)

        # NEW: list coercion from comma-separated strings
        if type_hint is list:
            # Try JSON first (handles ["a","b","c"])
            stripped = value.strip()
            if stripped.startswith("["):
                import json

                try:
                    return json.loads(stripped)
                except (json.JSONDecodeError, ValueError):
                    pass
            # Fallback: comma-separated
            return [item.strip() for item in value.split(",") if item.strip()]

        # NEW: dict coercion from key=value strings or JSON
        if type_hint is dict:
            stripped = value.strip()
            if stripped.startswith("{"):
                import json

                try:
                    return json.loads(stripped)
                except (json.JSONDecodeError, ValueError):
                    pass
            # Fallback: key=val,key=val
            result = {}
            for pair in value.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    result[k.strip()] = v.strip()
            return result if result else value

    return value


def solidify(
    data: Dict[str, Any],
    target: Type,
    source: str = "unknown",
    check: Optional[List[str]] = None,
    strict: bool = False,
    coerce: bool = True,
):
    """Converts loose data (dict) into a typed config instance.

    Args:
        data: Input data dict.
        target: Target @layer_obj class.
        source: Source tag for tracking (e.g. "config.yml", "cli").
        check: If provided, validate these categories immediately after loading.
        strict: If True, raise StructureError on unknown keys.
        coerce: If True, attempt type coercion based on field type hints.

    Returns:
        An instance of target with values set from data.
    """
    instance = target()

    for key, value in data.items():
        # Handle kebab-case and SCREAMING_SNAKE_CASE to snake_case
        normalized_key = key.replace("-", "_").lower()

        if normalized_key in instance._field_defs:
            fdef = instance._field_defs[normalized_key]

            # Nested @layer_obj: recursively solidify if value is a dict
            if _is_layer_obj_type(fdef.type_hint) and isinstance(value, dict):
                nested = solidify(value, fdef.type_hint, source=source, coerce=coerce)
                setattr(instance, normalized_key, nested)
                instance._sources[normalized_key].push(source, nested)
            else:
                # Coerce if requested
                if coerce and fdef.type_hint is not None:
                    try:
                        value = _coerce(value, fdef.type_hint, parser=fdef.parser)
                    except (ValueError, TypeError):
                        pass  # Leave as-is if coercion fails

                setattr(instance, normalized_key, value)
                instance._sources[normalized_key].push(source, value)

        elif strict:
            raise StructureError(f"Unknown key '{key}' found in source '{source}'")

    if check:
        instance.validate(check).raise_if_invalid()

    return instance


def solidify_env(
    prefix: str,
    target: Type,
    key_map: Optional[Dict[str, Any]] = None,
    separator: str = "_",
):
    """Loads configuration from environment variables.

    Args:
        prefix: Env var prefix (e.g. "AK" -> reads AK_ENDPOINT, AK_DEBUG, etc.)
        target: Target @layer_obj class.
        key_map: Optional dict mapping field names to custom env var names.
            Values can be a string (single env var) or list of strings (fallback chain).
        separator: Separator between prefix and field name (default "_").

    Returns:
        An instance of target with values set from environment variables.
    """
    instance = target()
    key_map = key_map or {}

    for name, fdef in instance._field_defs.items():
        # Nested @layer_obj: use a sub-prefix
        if _is_layer_obj_type(fdef.type_hint):
            sub_prefix = f"{prefix.upper()}{separator}{name.upper()}"
            nested = solidify_env(sub_prefix, fdef.type_hint, separator=separator)
            # Only layer if any field was actually set from env
            has_env_values = any(s != "default" for s in nested._sources.values())
            if has_env_values:
                current = getattr(instance, name)
                current.layer(nested)
                instance._sources[name].push(f"env:{sub_prefix}_*", current)
            continue

        # Check custom mapping first
        env_keys = key_map.get(name)
        if isinstance(env_keys, str):
            env_keys = [env_keys]

        # Default mapping: PREFIX_FIELD_NAME
        if not env_keys:
            env_keys = [f"{prefix.upper()}{separator}{name.upper()}"]

        for env_key in env_keys:
            val = os.environ.get(env_key)
            if val is not None:
                coerced = _coerce(val, fdef.type_hint, parser=fdef.parser)
                setattr(instance, name, coerced)
                instance._sources[name].push(f"env:{env_key}", coerced)
                break  # Stop at first found in fallback chain

    return instance


# --- File helpers ---


def solidify_file(
    path: str,
    target: Type,
    source: str = None,
    check: Optional[List[str]] = None,
    strict: bool = False,
    coerce: bool = True,
):
    """Load a config file (YAML, JSON, or TOML) and solidify it into a typed config.

    Detects format from file extension. Requires the corresponding library
    to be installed (PyYAML for .yml/.yaml, tomllib/tomli for .toml).

    Args:
        path: Path to the config file.
        target: Target @layer_obj class.
        source: Source tag. Defaults to the file path.
        check: Categories to validate after loading.
        strict: Raise on unknown keys.
        coerce: Attempt type coercion.

    Returns:
        An instance of target.

    Raises:
        FileNotFoundError: If path doesn't exist.
        StructureError: If file format is unsupported or parsing fails.
    """
    import os as _os

    if source is None:
        source = str(path)

    if not _os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    ext = str(path).rsplit(".", 1)[-1].lower() if "." in str(path) else ""

    if ext in ("yml", "yaml"):
        try:
            import yaml
        except ImportError:
            raise StructureError(
                "PyYAML is required to load .yml/.yaml files: pip install PyYAML"
            )
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}

    elif ext == "json":
        import json

        with open(path, "r") as f:
            data = json.load(f)

    elif ext == "toml":
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                raise StructureError(
                    "tomli is required to load .toml files on Python < 3.11: pip install tomli"
                )
        with open(path, "rb") as f:
            data = tomllib.load(f)

    else:
        raise StructureError(
            f"Unsupported config file format: '.{ext}'. Use .yml, .yaml, .json, or .toml"
        )

    if not isinstance(data, dict):
        raise StructureError(
            f"Config file '{path}' must contain a mapping at the top level"
        )

    return solidify(
        data, target, source=source, check=check, strict=strict, coerce=coerce
    )


def write_file(config, path: str, format: str = None):
    """Write a config object to a file.

    Args:
        config: A @layer_obj instance.
        path: Output file path.
        format: "yaml", "json", or "toml". Auto-detected from extension if None.
    """
    if format is None:
        ext = str(path).rsplit(".", 1)[-1].lower() if "." in str(path) else ""
        format = {"yml": "yaml", "yaml": "yaml", "json": "json", "toml": "toml"}.get(
            ext
        )

    data = config.to_dict()

    if format == "yaml":
        try:
            import yaml
        except ImportError:
            raise StructureError("PyYAML is required: pip install PyYAML")
        with open(path, "w") as f:
            yaml.dump(data, f, sort_keys=False, default_flow_style=False)

    elif format == "json":
        import json

        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    elif format == "toml":
        try:
            import tomli_w
        except ImportError:
            raise StructureError(
                "tomli_w is required to write .toml files: pip install tomli-w"
            )
        with open(path, "wb") as f:
            tomli_w.dump(data, f)

    else:
        raise StructureError(f"Unsupported format: '{format}'. Use yaml, json, or toml")
