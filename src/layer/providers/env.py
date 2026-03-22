"""EnvProvider — reads config from environment variables with a prefix."""

import os

from .base import BaseProvider


class EnvProvider(BaseProvider):
    """Reads configuration from environment variables matching a prefix.

    Environment variable names are expected to be PREFIX_FIELD_NAME (uppercase).
    Keys in the returned dict are lowercase field names with the prefix stripped.

    Args:
        prefix: Env var prefix (e.g. "APP" reads APP_HOST, APP_PORT, etc.)
        separator: Separator between prefix and field name (default "_").
    """

    def __init__(self, prefix: str, separator: str = "_"):
        self._prefix = prefix.rstrip(separator).upper()
        self._separator = separator

    def read(self) -> dict:
        result = {}
        prefix = self._prefix + self._separator
        for key, value in os.environ.items():
            if key.startswith(prefix):
                field_name = key[len(prefix) :].lower()
                result[field_name] = value
        return result

    @property
    def source_name(self) -> str:
        return f"env:{self._prefix}{self._separator}*"
