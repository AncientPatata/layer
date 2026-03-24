"""EnvProvider — reads config from environment variables and .env files."""

import os

from .base import BaseProvider


class EnvProvider(BaseProvider):
    """Reads configuration from environment variables and/or a .env file.

    Features:
    - Unified interface for both system environment variables and .env files.
    - Schema-aware deep mapping: automatically un-flattens variables to match
      nested @layerclass schemas.
    - Explicit overrides: respects `env="MY_VAR"` mapped directly on fields,
      ignoring the global prefix.
    - State isolation: reading a .env file will not mutate the global `os.environ`.
    - Strict precedence: system environment variables always win over .env files.

    Args:
        prefix: Env var prefix (e.g. "APP_" reads APP_HOST, APP_PORT, etc.)
        env_file: Optional path to a .env file.
        ignore_missing: If True (default), silently falls back to system env
            if the `env_file` is missing. If False, raises FileNotFoundError.
        separator: Separator between prefix and field name (default "_").
    """

    def __init__(
        self,
        prefix: str,
        env_file: str | None = None,
        ignore_missing: bool = True,
        separator: str = "_",
    ):
        self._prefix = prefix
        self._env_file = env_file
        self._ignore_missing = ignore_missing
        self._separator = separator
        self._schema = None

    def bind_schema(self, schema: type) -> None:
        self._schema = schema

    def read(self) -> dict:
        env_pool = {}

        # 1. Load .env file into pool (without mutating os.environ)
        if self._env_file:
            if not os.path.exists(self._env_file):
                if not self._ignore_missing:
                    raise FileNotFoundError(f"Environment file not found: {self._env_file}")
            else:
                try:
                    from dotenv import dotenv_values
                except ImportError:
                    from ..exceptions import MissingDependencyError

                    raise MissingDependencyError(
                        "python-dotenv is required to load .env files:"
                        + " pip install layerconf[dotenv]"
                    )
                env_pool.update(dotenv_values(self._env_file))

        # 2. Layer system os.environ on top (system takes precedence)
        env_pool.update(os.environ)

        # 3. Resolve to nested dictionary based on schema
        if self._schema:
            return self._resolve_schema(self._schema, self._prefix, env_pool)
        else:
            # Fallback: simple prefix stripping if no schema bound
            return self._resolve_flat(env_pool)

    def _resolve_schema(self, cls, prefix: str, env_pool: dict) -> dict:
        from ..solidify import _is_layer_obj_type

        result = {}

        # Ensure base_prefix doesn't have a trailing separator,
        # but if it's not empty, add one to construct keys
        base_prefix = prefix.rstrip(self._separator).upper()

        for name, fdef in cls._field_defs.items():
            if _is_layer_obj_type(fdef.type_hint):
                sub_prefix = (
                    f"{base_prefix}{self._separator}{name.upper()}"
                    if base_prefix
                    else f"{name.upper()}"
                )
                nested = self._resolve_schema(fdef.type_hint, sub_prefix, env_pool)
                if nested:
                    result[name] = nested
                continue

            val = None
            if fdef.env and fdef.env in env_pool:
                val = env_pool[fdef.env]
            else:
                env_key = (
                    f"{base_prefix}{self._separator}{name.upper()}" if base_prefix else name.upper()
                )
                if env_key in env_pool:
                    val = env_pool[env_key]

            if val is not None:
                result[name] = val

        return result

    def _resolve_flat(self, env_pool: dict) -> dict:
        result = {}
        prefix_upper = self._prefix.upper()
        if prefix_upper and not prefix_upper.endswith(self._separator):
            prefix_upper += self._separator

        for k, v in env_pool.items():
            if prefix_upper and k.startswith(prefix_upper):
                field_name = k[len(prefix_upper) :].lower()
                result[field_name] = v
            elif not prefix_upper:
                # If prefix is empty, return all (careful, usually not wanted but supported)
                result[k.lower()] = v
        return result

    @property
    def source_name(self) -> str:
        if self._env_file:
            return f"env:{self._env_file}|{self._prefix}{self._separator}*"
        return f"env:{self._prefix}{self._separator}*"
