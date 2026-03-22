"""Exporters — generate deployment artifacts from @layerclass definitions.

Pure functions that read a ``@layerclass`` schema and produce standard
deployment artifacts: JSON Schema, ``.env`` templates, and Kubernetes
ConfigMap YAML.

Example:
    from layer import exporters

    print(exporters.to_dotenv_template(AppConfig, prefix="APP"))
    print(exporters.to_configmap(AppConfig, name="my-app-config"))
"""


def to_json_schema(config_cls: type) -> dict:
    """Return the JSON Schema dict for a ``@layerclass``.

    Wraps ``config_cls.json_schema()`` and returns the result directly.

    Args:
        config_cls: A ``@layerclass`` decorated class.

    Returns:
        A JSON Schema dict (draft-07).
    """
    return config_cls.json_schema()


def to_dotenv_template(config_cls: type, prefix: str = "") -> str:
    """Generate a ``.env`` file template from a ``@layerclass`` definition.

    Each field becomes one ``KEY=<default>`` line, with its description emitted
    as a ``# comment`` above the line. Nested ``@layerclass`` fields are rendered
    as a labelled section. Secret fields have their default replaced with
    ``<secret>``.

    Args:
        config_cls: A ``@layerclass`` decorated class.
        prefix: Optional env var prefix (e.g. ``"APP"`` → ``APP_HOST=localhost``).

    Returns:
        A multi-line string suitable for saving as ``.env.template``.

    Example:
        @layerclass
        class Config:
            host: str = field(str, default="localhost", description="Database host")
            port: int = field(int, default=5432)

        print(to_dotenv_template(Config, prefix="APP"))
        # # Database host
        # APP_HOST=localhost
        # APP_PORT=5432
    """
    lines = []
    _render_dotenv_fields(config_cls, prefix.upper(), lines)
    return "\n".join(lines)


def _render_dotenv_fields(config_cls, prefix: str, lines: list) -> None:
    """Recursively render fields from a @layerclass into dotenv lines."""
    from .core import _is_layerclass

    for name, fdef in config_cls._field_defs.items():
        if _is_layerclass(fdef.type_hint):
            # Nested section header
            section_prefix = f"{prefix}_{name.upper()}" if prefix else name.upper()
            lines.append("")
            lines.append(f"# --- {fdef.type_hint.__name__} ---")
            _render_dotenv_fields(fdef.type_hint, section_prefix, lines)
            continue

        var_name = f"{prefix}_{name.upper()}" if prefix else name.upper()

        # Also respect fdef.env override
        if fdef.env:
            var_name = fdef.env

        if fdef.description:
            lines.append(f"# {fdef.description}")

        if fdef.secret:
            default_str = "<secret>"
        elif fdef.default is None:
            default_str = ""
        else:
            default_str = str(fdef.default)

        lines.append(f"{var_name}={default_str}")


def to_yaml(config_cls: type) -> str:
    """Generate a YAML configuration template from a ``@layerclass``.

    Non-secret fields are emitted with their default values. Secret fields
    are omitted and replaced with a commented-out placeholder. Field
    descriptions are emitted as YAML comments above the fields.

    Args:
        config_cls: A ``@layerclass`` decorated class.

    Returns:
        A YAML string suitable for saving as ``config.yml``.

    Example:
        print(to_yaml(AppConfig))
        # # Database host
        # host: localhost
        # port: 5432
    """
    lines = []
    _render_yaml_fields(config_cls, 0, lines)
    return "\n".join(lines)


def _render_yaml_fields(config_cls, indent: int, lines: list) -> None:
    """Recursively render fields from a @layerclass into YAML lines."""
    import yaml

    from .core import _is_layerclass

    prefix = "  " * indent

    for name, fdef in config_cls._field_defs.items():
        if _is_layerclass(fdef.type_hint):
            if fdef.description:
                for desc_line in fdef.description.split("\n"):
                    lines.append(f"{prefix}# {desc_line}")
            lines.append(f"{prefix}{name}:")
            _render_yaml_fields(fdef.type_hint, indent + 1, lines)
            continue

        if fdef.description:
            for desc_line in fdef.description.split("\n"):
                lines.append(f"{prefix}# {desc_line}")

        if fdef.secret:
            lines.append(f"{prefix}# {name}: <secret>")
            continue

        val_dump = yaml.dump(
            {name: fdef.default}, default_flow_style=False, sort_keys=False
        ).rstrip()
        for line in val_dump.split("\n"):
            lines.append(f"{prefix}{line}")


def to_configmap(config_cls: type, name: str = "app-config") -> str:
    """Generate a Kubernetes ConfigMap YAML string from a ``@layerclass``.

    Non-secret fields are emitted as ConfigMap data entries. Secret fields
    are omitted with a comment indicating they belong in a Secret resource.

    Args:
        config_cls: A ``@layerclass`` decorated class.
        name: The ``metadata.name`` for the ConfigMap resource
            (default ``"app-config"``).

    Returns:
        A YAML string suitable for ``kubectl apply -f``.

    Example:
        print(to_configmap(AppConfig, name="my-app"))
        # apiVersion: v1
        # kind: ConfigMap
        # metadata:
        #   name: my-app
        # data:
        #   HOST: localhost
        #   PORT: "5432"
    """
    lines = [
        "apiVersion: v1",
        "kind: ConfigMap",
        "metadata:",
        f"  name: {name}",
        "data:",
    ]
    _render_configmap_fields(config_cls, "", lines)
    return "\n".join(lines)


def _render_configmap_fields(config_cls, prefix: str, lines: list) -> None:
    """Recursively render fields from a @layerclass into ConfigMap data lines."""
    from .core import _is_layerclass

    for name, fdef in config_cls._field_defs.items():
        if _is_layerclass(fdef.type_hint):
            nested_prefix = f"{prefix}{name.upper()}_" if prefix else f"{name.upper()}_"
            _render_configmap_fields(fdef.type_hint, nested_prefix, lines)
            continue

        key = f"{prefix}{name.upper()}"

        if fdef.secret:
            lines.append(f"  # {key}: <omitted — use a Secret resource>")
            continue

        if fdef.default is None:
            value_str = ""
        else:
            value_str = str(fdef.default)

        # YAML: quote values that look like numbers to preserve string type
        if value_str.isdigit() or (value_str.replace(".", "", 1).isdigit() and "." in value_str):
            lines.append(f'  {key}: "{value_str}"')
        else:
            lines.append(f"  {key}: {value_str}")
