import os
from enum import Enum
from typing import Type, Dict, Any, Optional, List
from .exceptions import StructureError, CoercionError
from .type_resolution import coerce as _coerce


class SolidifyMode(Enum):
    """Strictness mode for solidify() and ConfigPipeline.

    LAX:
        Unknown keys are silently ignored.
        Type coercion errors are swallowed; the raw value is used as-is.
    STANDARD (default):
        Unknown keys are silently ignored.
        Type coercion errors bubble up as CoercionError.
    STRICT:
        Unknown keys immediately raise StructureError.
        No coercion is attempted; incoming values must already match the type hint.
    """

    LAX = "lax"
    STANDARD = "standard"
    STRICT = "strict"


def _is_layer_obj_type(cls):
    """Check if a type is a @layerclass decorated class."""
    return (
        isinstance(cls, type)
        and hasattr(cls, "_field_defs")
        and (hasattr(cls, "_is_layerclass_marker") or hasattr(cls, "_is_layer_obj_marker"))
    )


def solidify(
    data: Dict[str, Any],
    target: Type,
    source: str = "unknown",
    check: Optional[List[str]] = None,
    strict: bool = False,
    coerce: bool = True,
    mode: Optional["SolidifyMode"] = None,
):
    """Converts loose data (dict) into a typed config instance.

    Args:
        data: Input data dict.
        target: Target @layer_obj class.
        source: Source tag for tracking (e.g. "config.yml", "cli").
        check: If provided, validate these categories immediately after loading.
        strict: If True, raise StructureError on unknown keys. (Legacy; prefer mode=)
        coerce: If True, attempt type coercion based on field type hints. (Legacy; prefer mode=)
        mode: SolidifyMode controlling strictness. Overrides strict/coerce when set.
            LAX — unknown keys ignored, coercion errors swallowed.
            STANDARD — unknown keys ignored, CoercionError bubbles.
            STRICT — unknown keys raise StructureError, no coercion.

    Returns:
        An instance of target with values set from data.
    """
    # mode takes precedence over legacy strict/coerce kwargs
    if mode is not None:
        strict = mode == SolidifyMode.STRICT
        coerce = mode != SolidifyMode.STRICT

    instance = target()

    # Pre-compute reverse alias map: alias_string -> canonical field name
    alias_map: Dict[str, str] = {}
    for field_name, fdef in instance._field_defs.items():
        if fdef.alias:
            alias_map[fdef.alias] = field_name
        for a in fdef.aliases:
            alias_map[a] = field_name

    for key, value in data.items():
        # Resolve canonical field name: try exact match, then alias map, then kebab/case normalization
        normalized_key = key.replace("-", "_").lower()
        if normalized_key in instance._field_defs:
            field_name = normalized_key
        elif key in alias_map:
            field_name = alias_map[key]
        elif normalized_key in alias_map:
            field_name = alias_map[normalized_key]
        elif strict:
            raise StructureError(f"Unknown key '{key}' found in source '{source}'")
        else:
            continue

        fdef = instance._field_defs[field_name]

        # Nested @layer_obj: recursively solidify if value is a dict
        if _is_layer_obj_type(fdef.type_hint) and isinstance(value, dict):
            nested = solidify(value, fdef.type_hint, source=source, coerce=coerce, mode=mode)
            setattr(instance, field_name, nested)
            instance._sources[field_name].push(source, nested)
        else:
            # Coerce if requested
            if coerce and fdef.type_hint is not None:
                try:
                    value = _coerce(value, fdef.type_hint, parser=fdef.parser)
                except (ValueError, TypeError, CoercionError):
                    if mode == SolidifyMode.STANDARD:
                        raise  # STANDARD: let coercion errors bubble
                    # LAX or legacy (mode=None): swallow and leave as-is

            # Apply @parser methods (after coercion, before write)
            for parse_fn in type(instance)._parsers.get(field_name, []):
                value = parse_fn(instance, value)

            setattr(instance, field_name, value)
            instance._sources[field_name].push(source, value)

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

        # Determine env var name(s) to check, in priority order:
        # 1. fdef.env (explicit override on the field)
        # 2. key_map (caller-supplied override)
        # 3. PREFIX_FIELD_NAME convention
        if fdef.env:
            env_keys = [fdef.env]
        else:
            env_keys = key_map.get(name)
            if isinstance(env_keys, str):
                env_keys = [env_keys]
            if not env_keys:
                env_keys = [f"{prefix.upper()}{separator}{name.upper()}"]

        for env_key in env_keys:
            val = os.environ.get(env_key)
            if val is not None:
                coerced = _coerce(val, fdef.type_hint, parser=fdef.parser)
                # Apply @parser methods (after coercion, before write)
                for parse_fn in type(instance)._parsers.get(name, []):
                    coerced = parse_fn(instance, coerced)
                setattr(instance, name, coerced)
                instance._sources[name].push(f"env:{env_key}", coerced)
                break  # Stop at first found in fallback chain

    return instance


# --- File helpers ---


def _read_file(path: str, fmt: str | None = None) -> dict:
    """Parse a config file and return its contents as a dict.

    Supports .yml/.yaml, .json, and .toml formats. Detects format from
    file extension unless overridden by fmt.

    Args:
        path: Path to the config file.
        fmt: Explicit format override: ``"yaml"``, ``"json"``, or ``"toml"``.
            Use when the filename has no recognisable extension.

    Returns:
        Parsed file contents as a dict.

    Raises:
        FileNotFoundError: If path doesn't exist.
        StructureError: If file format is unsupported or parsing fails.
    """
    import os as _os

    if not _os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    if fmt is not None:
        ext = fmt.lower().lstrip(".")
    else:
        ext = str(path).rsplit(".", 1)[-1].lower() if "." in str(path) else ""

    if ext in ("yml", "yaml"):
        try:
            import yaml
        except ImportError:
            raise StructureError("PyYAML is required to load .yml/.yaml files: pip install PyYAML")
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
        raise StructureError(f"Config file '{path}' must contain a mapping at the top level")

    return data


def solidify_file(
    path: str,
    target: Type,
    source: str = None,
    check: Optional[List[str]] = None,
    strict: bool = False,
    coerce: bool = True,
    mode: Optional["SolidifyMode"] = None,
):
    """Load a config file (YAML, JSON, or TOML) and solidify it into a typed config.

    Detects format from file extension. Requires the corresponding library
    to be installed (PyYAML for .yml/.yaml, tomllib/tomli for .toml).

    Args:
        path: Path to the config file.
        target: Target @layer_obj class.
        source: Source tag. Defaults to the file path.
        check: Categories to validate after loading.
        strict: Raise on unknown keys. (Legacy; prefer mode=)
        coerce: Attempt type coercion. (Legacy; prefer mode=)
        mode: SolidifyMode controlling strictness. Overrides strict/coerce when set.

    Returns:
        An instance of target.

    Raises:
        FileNotFoundError: If path doesn't exist.
        StructureError: If file format is unsupported or parsing fails.
    """
    if source is None:
        source = str(path)

    data = _read_file(path)

    return solidify(
        data,
        target,
        source=source,
        check=check,
        strict=strict,
        coerce=coerce,
        mode=mode,
    )


def write_file(config, path: str, format: str = None, by_alias: bool = False):
    """Write a config object to a file.

    Args:
        config: A @layer_obj instance.
        path: Output file path.
        format: "yaml", "json", or "toml". Auto-detected from extension if None.
        by_alias: If True, use field aliases as keys in the output file.
    """
    if format is None:
        ext = str(path).rsplit(".", 1)[-1].lower() if "." in str(path) else ""
        format = {"yml": "yaml", "yaml": "yaml", "json": "json", "toml": "toml"}.get(ext)

    data = config.to_dict(by_alias=by_alias)

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
            raise StructureError("tomli_w is required to write .toml files: pip install tomli-w")
        with open(path, "wb") as f:
            tomli_w.dump(data, f)

    else:
        raise StructureError(f"Unsupported format: '{format}'. Use yaml, json, or toml")
