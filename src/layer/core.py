import dataclasses
from collections import defaultdict
from copy import deepcopy
from typing import Any

from .interpolation import resolve_all
from .layering import LayerRule
from .sources import SourceHistory
from .validation import ValidationError, ValidationResult

_REDACTED = "***"


class FieldDef:
    """Metadata about a single configuration field."""

    def __init__(
        self,
        type_hint: type,
        default: Any = None,
        categories: dict[str, list] = None,
        meta: dict[str, Any] = None,
        description: str = None,
        secret: bool = False,
        parser: Any = None,
        alias: str = None,
        aliases: list[str] = None,
        env: str = None,
        reloadable: bool = True,
    ):
        self.type_hint = type_hint
        self.default = default
        self.categories = categories or {}
        self.meta = meta or {}
        self.description = description
        self.secret = secret
        self.parser = parser
        self.alias = alias
        self.aliases = aliases or []
        self.env = env
        self.reloadable = reloadable


def field(
    type_hint: type,
    *uncategorized_rules,
    default: Any = None,
    meta: dict[str, Any] = None,
    description: str = None,
    secret: bool = False,
    parser: Any = None,
    alias: str = None,
    aliases: list[str] = None,
    env: str = None,
    reloadable: bool = True,
    **category_rules,
) -> Any:
    """Declares a configuration field with optional validation rules.

    Args:
        type_hint: The expected type of the field.
        *uncategorized_rules: Validators that always run (bare rules).
        default: Default value for the field.
        meta: Arbitrary metadata dict (e.g. {"cli_option": click.option(...)}).
        description: Human-readable description of the field.
        alias: Alternate name used when loading from dicts/JSON/YAML (e.g. "apiKey").
        aliases: Additional fallback names tried in order after alias.
        env: Explicit environment variable name, overrides PREFIX_FIELD_NAME convention.
        **category_rules: Named categories mapping to lists of validators.
            e.g. cluster=[require], common=[one_of("json", "yaml")]

    Returns:
        A FieldDef instance (replaced by the default value after @layer_obj processes it).
    """
    categories = {"_bare": list(uncategorized_rules)}
    categories.update(category_rules)
    return FieldDef(
        type_hint,
        default,
        categories,
        meta,
        description,
        secret=secret,
        parser=parser,
        alias=alias,
        aliases=aliases,
        env=env,
        reloadable=reloadable,
    )


def parser(*field_names, before_coerce=False):
    """Marks a method as a data parser for the specified field(s).

    By default, the method is called after type coercion but before the value is
    written to the field. If `before_coerce=True` is provided, it runs before
    the value is coerced by the type resolution engine.

    The method receives the current value and must return the transformed value.
    It runs during solidify(), solidify_env(), and set().

    Usage:
        @parser("endpoint")
        def _clean_endpoint(self, value: str) -> str:
            return value.strip().rstrip("/")

        @parser("status", before_coerce=True)
        def _parse_status(self, value: Any) -> str:
            if isinstance(value, dict) and "status" in value:
                return value["status"]
            return value
    """

    def decorator(fn):
        fn._layer_parser_fields = field_names
        fn._layer_parser_before_coerce = before_coerce
        return fn

    return decorator


def validator(*field_names, categories=None):
    """Marks a method as a stateful validator for the specified field(s).

    Called once per listed field during validate(). The method receives
    (self, field_name, value) and should raise ValidationError if invalid.
    If categories is omitted the validator runs on every validate() call (bare).

    Usage:
        @validator("cert_path", "key_path")
        def _files_exist(self, field_name, value):
            if value and not os.path.exists(value):
                raise ValidationError(field_name, "File not found", "path_check", "bare")

        @validator("cert_path", categories=["production"])
        def _certs_match(self, field_name, value):
            ...
    """

    def decorator(fn):
        fn._layer_validator_fields = field_names
        fn._layer_validator_categories = list(categories or [])
        return fn

    return decorator


def root_validator(categories=None):
    """Marks a method as a cross-field (root) validator.

    Called at the end of validate() with no arguments besides self. Should
    raise ConfigError (or ValidationError) if the overall state is invalid.
    If categories is omitted the validator runs on every validate() call.

    Usage:
        @root_validator(categories=["database"])
        def _check_connection(self):
            if self.dsn and self.host:
                raise ConfigError("Cannot specify both 'dsn' and 'host'.")
    """

    def decorator(fn):
        fn._layer_root_validator = True
        fn._layer_validator_categories = list(categories or [])
        return fn

    return decorator


def computed_field(fn):
    """Marks a method as a computed (read-only, dynamic) field.

    The decorated method is exposed as a property evaluated on each access and
    is automatically included in ``to_dict()`` and ``explain()``. Attempting to
    assign a value to a computed field raises ``AttributeError``.

    Args:
        fn: The method to promote to a computed field. Must accept only ``self``
            and should include a return-type annotation so ``explain()`` can
            report the type.

    Returns:
        The same callable with ``_layer_computed = True`` set; the
        ``@layerclass`` decorator later replaces it with a ``property``.

    Example:
        @layerclass
        class ServiceConfig:
            timeout_base: int = field(int, default=10)
            retry_count: int = field(int, default=3)

            @computed_field
            def total_timeout(self) -> int:
                \"\"\"Total max wait across all retries.\"\"\"
                return self.timeout_base * self.retry_count
    """
    fn._layer_computed = True
    return fn


def _is_layerclass(cls_or_instance):
    """Check if something is a @layerclass decorated class or instance of one."""
    cls = cls_or_instance if isinstance(cls_or_instance, type) else type(cls_or_instance)
    return hasattr(cls, "_field_defs") and hasattr(cls, "_is_layerclass_marker")


# Backward-compatibility alias
_is_layer_obj = _is_layerclass


def _maybe_redact(value, fdef: FieldDef, redact: bool = True) -> Any:
    """Return redacted placeholder if the field is secret and redaction is on."""
    if redact and fdef.secret and value is not None:
        return _REDACTED
    return value


def layerclass(cls):
    """Converts a plain class into a layered configuration object.

    The decorated class gains full support for deterministic multi-source
    config merging: load values from files, environment variables, and remote
    stores; merge them in priority order; resolve ``${variable}`` references;
    validate by category; and freeze the result for safe sharing across threads.

    Methods added to the class:
        layer(other, rules=None): Merge another config on top. Nested
            ``@layerclass`` fields are recursively merged. ``rules`` is a
            ``{field_name: LayerRule}`` dict controlling merge strategy
            (OVERRIDE, PRESERVE, MERGE, APPEND).
        validate(categories=None, fields=None): Run validation rules.
            Pass a list of category names to run only those; ``None`` runs
            bare (uncategorized) rules only; ``"*"`` runs everything.
        resolve(): Resolve all ``${field_name}`` interpolations in-place.
        copy(): Deep copy the config instance.
        to_dict(redact=False, by_alias=False): Export as a plain dict.
        explain(full_history=False, redact=True): Structured info about
            current values, sources, and types—great for debugging.
        diff(other): Compare two configs; returns a list of changed fields.
        freeze() / frozen: Prevent further mutation of field values.
        json_schema(): Generate a JSON Schema dict from field definitions.
        get(field, default=None): Dot-notation field access with fallback.
        set(field, value, strict=False, source="set()"): Dot-notation setter
            with optional immediate single-field validation.

    Class-level attributes added:
        _field_defs: ``{name: FieldDef}`` schema from ``field()`` declarations.
        _sources: Per-instance ``{name: SourceHistory}`` tracking provenance.
        _computed_fields: ``{name: fn}`` for ``@computed_field`` methods.

    Example:
        @layerclass
        class DatabaseConfig:
            host: str = field(str, default="localhost", description="DB host")
            port: int = field(int, default=5432, server=[require, is_port])
            url: str = field(str, default="${host}:${port}")

            @computed_field
            def dsn(self) -> str:
                return f"postgresql://{self.host}:{self.port}/mydb"
    """

    # Single pass: harvest FieldDefs, @parser, @validator, @root_validator, @computed_field
    field_defs = {}
    parsers = {}  # field_name -> [fn, ...]
    method_validators = []  # [(field_names_tuple, categories_list, fn), ...]
    root_validators = []  # [(categories_list, fn), ...]
    computed_fields = {}  # attr_name -> fn

    for attr_name in list(cls.__dict__.keys()):
        attr_value = cls.__dict__[attr_name]
        if isinstance(attr_value, FieldDef):
            field_defs[attr_name] = attr_value
            delattr(cls, attr_name)
        elif callable(attr_value):
            if hasattr(attr_value, "_layer_computed"):
                computed_fields[attr_name] = attr_value
                # Replace with a property so it evaluates dynamically
                setattr(cls, attr_name, property(attr_value))
            elif hasattr(attr_value, "_layer_parser_fields"):
                for fname in attr_value._layer_parser_fields:
                    parsers.setdefault(fname, []).append(attr_value)
                delattr(cls, attr_name)
            elif hasattr(attr_value, "_layer_validator_fields"):
                method_validators.append(
                    (
                        attr_value._layer_validator_fields,
                        attr_value._layer_validator_categories,
                        attr_value,
                    )
                )
                delattr(cls, attr_name)
            elif hasattr(attr_value, "_layer_root_validator"):
                root_validators.append(
                    (
                        attr_value._layer_validator_categories,
                        attr_value,
                    )
                )
                delattr(cls, attr_name)

    class WrappedConfig(cls):
        # Class-level attributes — accessible without instantiation
        _field_defs = field_defs
        _is_layerclass_marker = True
        _is_layer_obj_marker = True  # backward compat
        _parsers = parsers
        _method_validators = method_validators
        _root_validators = root_validators
        _computed_fields = computed_fields

        def __init__(self, **kwargs):
            self._sources = defaultdict(SourceHistory)
            self._frozen = False

            # Initialize with defaults
            for name, fdef in self._field_defs.items():
                if _is_layer_obj(fdef.type_hint):
                    # Nested @layer_obj: create a default instance
                    setattr(
                        self,
                        name,
                        fdef.default.copy() if fdef.default is not None else fdef.type_hint(),
                    )
                else:
                    setattr(self, name, fdef.default)
                self._sources[name].push("default", fdef.default)

            # Apply kwargs (usually from solidify)
            for k, v in kwargs.items():
                if k in self._field_defs:
                    setattr(self, k, v)

        def __setattr__(self, name, value):
            # Allow internal attributes
            if name.startswith("_"):
                super().__setattr__(name, value)
                return
            # Guard computed fields
            if name in type(self)._computed_fields:
                raise AttributeError(f"Cannot set computed field '{name}'")
            # Check frozen
            if hasattr(self, "_frozen") and self._frozen and name in self._field_defs:
                raise AttributeError(f"Cannot modify '{name}': config is frozen")
            super().__setattr__(name, value)

        def layer(self, other: "WrappedConfig", rules=None):
            """Merge another config on top of this one.

            For nested @layer_obj fields, recursively layers the sub-config.
            """
            rules = rules or {}
            for name in self._field_defs:
                other_source = other._sources[name].current if name in other._sources else "default"

                # Skip fields that weren't explicitly set in 'other'
                if other_source == "default":
                    continue

                other_val = getattr(other, name, None)
                base_val = getattr(self, name, None)
                rule = rules.get(name, LayerRule.OVERRIDE)

                # Nested layer_obj: recurse
                fdef = self._field_defs[name]
                if (
                    _is_layer_obj(fdef.type_hint)
                    and _is_layer_obj(base_val)
                    and _is_layer_obj(other_val)
                ):
                    nested_rules = rules.get(name) if isinstance(rules.get(name), dict) else None
                    base_val.layer(other_val, rules=nested_rules)
                    # Merge source info: mark as the other source since it was touched
                    self._sources[name].push(other_source, getattr(self, name).copy())
                    continue

                if callable(rule) and not isinstance(rule, LayerRule):
                    setattr(self, name, rule(base_val, other_val))
                elif rule == LayerRule.PRESERVE:
                    continue
                elif rule == LayerRule.MERGE:
                    if isinstance(base_val, dict) and isinstance(other_val, dict):
                        setattr(self, name, {**base_val, **other_val})
                    else:
                        setattr(self, name, other_val)
                elif rule == LayerRule.APPEND:
                    if isinstance(base_val, list) and isinstance(other_val, list):
                        setattr(self, name, base_val + other_val)
                    else:
                        setattr(self, name, other_val)
                else:  # OVERRIDE (default)
                    setattr(self, name, other_val)

                self._sources[name].push(other_source, getattr(self, name))

                # TODO: changes with the source change

            return self

        def resolve(self):
            """Resolve all ${...} variable interpolations in-place."""
            resolve_all(self)
            return self

        def source_of(self, field_name: str) -> str:
            """Return the current (most recent) source for a field."""
            return self._sources[field_name].current

        def source_history_of(self, field_name: str) -> list:
            """Return full source history for a field."""
            return self._sources[field_name].entries

        def validate(self, categories=None, fields=None):
            """Run validation rules for specific categories and/or fields.

            Args:
                categories: List of category names, "*" or ["*"] for all, None for bare only.
                fields: Optional list of field names to limit validation to.

            Returns:
                ValidationResult with errors (if any).
            """
            errors = []

            # Normalize categories
            if categories == "*":
                categories = ["*"]
            check_all = categories == ["*"] if categories else False
            cats_to_check = set(categories or [])

            for name, fdef in self._field_defs.items():
                # Field filter
                if fields is not None and name not in fields:
                    continue

                val = getattr(self, name)

                # Nested: recurse validation
                if _is_layer_obj(fdef.type_hint) and _is_layer_obj(val):
                    nested_result = val.validate(categories, fields=None)
                    for err in nested_result.errors:
                        # Prefix the field name for clarity
                        err.field = f"{name}.{err.field}"
                        errors.append(err)
                    continue

                # Collect rules to run
                rules_to_run = [("bare", r) for r in fdef.categories.get("_bare", [])]
                for cat, cat_rules in fdef.categories.items():
                    if cat == "_bare":
                        continue
                    if check_all or cat in cats_to_check:
                        rules_to_run.extend([(cat, r) for r in cat_rules])  # type: ignore[arg-type]

                # Execute rules
                for cat_name, rule in rules_to_run:
                    try:
                        rule(val, name, self)
                    except ValidationError as e:
                        e.category = cat_name
                        errors.append(e)

            # Phase 2: @validator methods
            for field_names, validator_cats, fn in self._method_validators:
                should_run = (
                    not validator_cats or check_all or bool(cats_to_check & set(validator_cats))
                )
                if not should_run:
                    continue
                for fname in field_names:
                    if fields is not None and fname not in fields:
                        continue
                    try:
                        fn(self, fname, getattr(self, fname))
                    except ValidationError as e:
                        errors.append(e)

            # Phase 3: @root_validator methods
            from .exceptions import ConfigError as _ConfigError

            for validator_cats, fn in self._root_validators:
                should_run = (
                    not validator_cats or check_all or bool(cats_to_check & set(validator_cats))
                )
                if not should_run:
                    continue
                try:
                    fn(self)
                except ValidationError as e:
                    errors.append(e)
                except _ConfigError as e:
                    errors.append(
                        ValidationError("__root__", str(e), fn.__name__, "root_validator")
                    )

            return ValidationResult(errors)

        def explain(self, full_history=False, redact: bool = True):
            info = []
            for name, fdef in self._field_defs.items():
                val = getattr(self, name)

                if _is_layer_obj(fdef.type_hint) and _is_layer_obj(val):
                    nested_info = val.explain(full_history=full_history)
                    for item in nested_info:
                        item["field"] = f"{name}.{item['field']}"
                    info.extend(nested_info)
                    continue

                categories = [c for c in fdef.categories.keys() if c != "_bare"]
                entry = {
                    "field": name,
                    "value": _maybe_redact(val, fdef, redact),
                    "source": self._sources[name].current,
                    "type": fdef.type_hint.__name__
                    if hasattr(fdef.type_hint, "__name__")
                    else str(fdef.type_hint),
                    "default": fdef.default,
                    "description": fdef.description,
                    "categories": categories,
                }
                if full_history:
                    entry["history"] = [
                        {
                            "source": e.source,
                            "value": _maybe_redact(e.value, fdef, redact),
                        }
                        for e in self._sources[name].entries
                    ]
                info.append(entry)
            # Computed fields
            import typing as _typing

            for name, fn in type(self)._computed_fields.items():
                return_type = _typing.get_type_hints(fn).get("return", _typing.Any)
                info.append(
                    {
                        "field": name,
                        "value": getattr(self, name),
                        "source": "computed",
                        "type": getattr(return_type, "__name__", str(return_type)),
                        "default": None,
                        "description": fn.__doc__,
                    }
                )
            return info

        def get(self, field_name: str, default: Any = None) -> Any:
            """Get a field value by name, with optional fallback.

            Supports dot-notation for nested configs: config.get("database.host")
            """
            if "." in field_name:
                parts = field_name.split(".", 1)
                nested = getattr(self, parts[0], None)
                if nested is not None and _is_layer_obj(nested):
                    return nested.get(parts[1], default)
                return default

            if field_name in self._field_defs:
                return getattr(self, field_name, default)
            return default

        def set(
            self,
            field_name: str,
            value: Any,
            strict: bool = False,
            source: str = "set()",
        ) -> None:
            """Set a field value with optional single-field validation.

            Args:
                field_name: Name of the field (supports dot-notation for nested).
                value: The value to set.
                strict: If True, run this field's validation rules immediately after
                        setting. Raises ValidationError on failure.
                source: Source tag for tracking (default "set()").

            Raises:
                AttributeError: If field doesn't exist or config is frozen.
                ValidationError: If strict=True and validation fails.
            """
            # Dot-notation for nested
            if "." in field_name:
                parts = field_name.split(".", 1)
                nested = getattr(self, parts[0], None)
                if nested is not None and _is_layer_obj(nested):
                    nested.set(parts[1], value, strict=strict, source=source)
                    return
                raise AttributeError(
                    f"Cannot set '{field_name}': '{parts[0]}' is not a nested config"
                )

            if field_name not in self._field_defs:
                raise AttributeError(f"Unknown field: '{field_name}'")

            fdef = self._field_defs[field_name]

            # Apply before_coerce parsers
            for parse_fn in type(self)._parsers.get(field_name, []):
                if getattr(parse_fn, "_layer_parser_before_coerce", False):
                    value = parse_fn(self, value)

            # Type coerce if the value is a string and the target isn't
            if isinstance(value, str) and fdef.type_hint is not str:
                from .solidify import _coerce

                value = _coerce(value, fdef.type_hint, parser=fdef.parser)

            # Apply @parser methods (after coercion, before write)
            for parse_fn in type(self)._parsers.get(field_name, []):
                if not getattr(parse_fn, "_layer_parser_before_coerce", False):
                    value = parse_fn(self, value)

            setattr(self, field_name, value)
            self._sources[field_name].push(source, value)

            # Single-field validation if strict
            if strict:
                result = self.validate(categories="*", fields=[field_name])
                result.raise_if_invalid()

        def copy(self):
            """Deep copy the config object."""
            new = self.__class__()
            for name, fdef in self._field_defs.items():
                val = getattr(self, name)
                if _is_layer_obj(fdef.type_hint) and _is_layer_obj(val):
                    setattr(new, name, val.copy())
                else:
                    setattr(new, name, deepcopy(val))
            new._sources = {k: deepcopy(v) for k, v in self._sources.items()}
            return new

        def to_dict(self, redact=False, by_alias=False):
            """Export current values as a plain dict. Recursively converts nested @layer_obj.

            Args:
                redact: If True, replace secret field values with "***".
                by_alias: If True, use each field's alias as the output key (falls back
                    to the field name when no alias is defined).

            Design note:
            to_dict() defaults to redact=False because it's often used for serialization
            back to disk.
            explain() defaults to redact=True because it's primarily a debugging/logging
            tool. The caller can always override.
            """
            result = {}
            for name, fdef in self._field_defs.items():
                out_key = (fdef.alias or name) if by_alias else name
                val = getattr(self, name)
                if _is_layer_obj(fdef.type_hint) and _is_layer_obj(val):
                    result[out_key] = val.to_dict(redact=redact, by_alias=by_alias)
                else:
                    val = _maybe_redact(val, fdef, redact)
                    if dataclasses.is_dataclass(val) and not isinstance(val, type):
                        result[out_key] = dataclasses.asdict(val)
                    elif hasattr(val, "model_dump"):  # Pydantic v2
                        result[out_key] = val.model_dump()
                    else:
                        result[out_key] = val
            # Computed fields — always included, never redacted
            for name in type(self)._computed_fields:
                result[name] = getattr(self, name)
            return result

        def diff(self, other, redact=True):
            """Compare this config with another, returning a list of differences.

            Args:
                other: Another config instance of the same type.

            Returns:
                List of dicts with field, old_value, new_value, old_source, new_source
                for each field that differs.
            """
            diffs = []
            for name, fdef in self._field_defs.items():
                self_val = getattr(self, name)
                other_val = getattr(other, name, None)

                if (
                    _is_layer_obj(fdef.type_hint)
                    and _is_layer_obj(self_val)
                    and _is_layer_obj(other_val)
                ):
                    nested_diffs = self_val.diff(other_val)
                    for d in nested_diffs:
                        d["field"] = f"{name}.{d['field']}"
                    diffs.extend(nested_diffs)
                    continue

                if self_val != other_val:
                    diffs.append(
                        {
                            "field": name,
                            "old_value": _maybe_redact(self_val, fdef, redact),
                            "new_value": _maybe_redact(other_val, fdef, redact),
                            "old_source": self._sources[name].current
                            if name in self._sources
                            else "unknown",
                            "new_source": other._sources[name].current
                            if name in other._sources
                            else "unknown",
                        }
                    )
            return diffs

        def freeze(self):
            """Freeze the config, preventing further mutation of field values.

            After calling freeze(), any attempt to set a field value will raise
            AttributeError. Internal attributes (prefixed with _) are unaffected.
            """
            # Recursively freeze nested configs
            for name, fdef in self._field_defs.items():
                val = getattr(self, name)
                if _is_layer_obj(fdef.type_hint) and _is_layer_obj(val):
                    val.freeze()
            self._frozen = True

        def _unfreeze_deep(self):
            """Recursively unfreeze this config and all nested layer_obj children."""
            self._frozen = False
            for name, fdef in self._field_defs.items():
                val = getattr(self, name)
                if _is_layer_obj(fdef.type_hint) and _is_layer_obj(val):
                    val._unfreeze_deep()

        @property
        def frozen(self):
            """Whether this config is frozen."""
            return self._frozen

        @classmethod
        def json_schema(cls):
            """Generate a JSON Schema dict from the field definitions.

            Handles nested @layer_obj types recursively. Includes description,
            default, and enum constraints from one_of validators.

            Returns:
                A dict conforming to JSON Schema draft-07.
            """
            _TYPE_MAP = {
                str: "string",
                int: "integer",
                float: "number",
                bool: "boolean",
                list: "array",
                dict: "object",
            }

            properties = {}
            required = []

            for name, fdef in cls._field_defs.items():
                # Nested @layer_obj
                if _is_layer_obj(fdef.type_hint):
                    prop = fdef.type_hint.json_schema()
                else:
                    json_type = _TYPE_MAP.get(fdef.type_hint, "string")
                    prop = {"type": json_type}

                # Description
                if fdef.description:
                    prop["description"] = fdef.description

                # Default
                if fdef.default is not None:
                    prop["default"] = fdef.default

                # Extract enum from one_of validators
                for cat_rules in fdef.categories.values():
                    for rule in cat_rules:
                        # one_of returns a closure named _one_of with __closure__
                        # containing the values
                        if hasattr(rule, "__name__") and rule.__name__ == "_one_of":
                            if rule.__closure__ and len(rule.__closure__) > 0:
                                allowed = rule.__closure__[0].cell_contents
                                if isinstance(allowed, tuple):
                                    prop["enum"] = list(allowed)

                # Extract in_range for minimum/maximum
                for cat_rules in fdef.categories.values():
                    for rule in cat_rules:
                        if hasattr(rule, "__name__") and rule.__name__ == "_in_range":
                            if rule.__closure__ and len(rule.__closure__) >= 2:
                                cells = [c.cell_contents for c in rule.__closure__]
                                # Closure ordering is alphabetical (hi, lo) — use min/max
                                numeric = [c for c in cells if isinstance(c, (int, float))]
                                if len(numeric) >= 2:
                                    prop["minimum"] = min(numeric)
                                    prop["maximum"] = max(numeric)

                # Check if required in any category
                for cat_rules in fdef.categories.values():
                    for rule in cat_rules:
                        if hasattr(rule, "__name__") and rule.__name__ == "require":
                            if name not in required:
                                required.append(name)

                properties[name] = prop

            schema = {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": properties,
            }
            if required:
                schema["required"] = required

            # Add title from class name
            schema["title"] = cls.__name__

            return schema

    WrappedConfig.__name__ = cls.__name__
    WrappedConfig.__qualname__ = cls.__qualname__
    return WrappedConfig


# Backward-compatibility alias
layer_obj = layerclass
