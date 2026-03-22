"""FileProvider — reads config from YAML, JSON, or TOML files."""

from .base import BaseProvider


class FileProvider(BaseProvider):
    """Reads configuration from a file on disk.

    Supports .yml/.yaml, .json, and .toml formats via the shared
    _read_file() helper in solidify.py.

    Args:
        path: Path to the config file.
        watch: If True, the pipeline can watch this file for hot-reloading.
    """

    def __init__(self, path: str, watch: bool = False):
        self._path = path
        self._watch = watch

    def read(self) -> dict:
        from layer.solidify import _read_file

        return _read_file(self._path)

    @property
    def source_name(self) -> str:
        return f"file:{self._path}"

    @property
    def watchable(self) -> bool:
        return self._watch
