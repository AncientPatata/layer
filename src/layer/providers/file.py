"""FileProvider — reads config from YAML, JSON, or TOML files."""

from .base import BaseProvider


class FileProvider(BaseProvider):
    """Reads configuration from a file on disk.

    Supports .yml/.yaml, .json, and .toml formats. Format is normally
    inferred from the file extension; use ``fmt`` to override when the
    filename has no recognisable extension (e.g. ``my.config``).

    Args:
        path: Path to the config file.
        watch: If True, the pipeline can watch this file for hot-reloading.
        fmt: Explicit format: ``"yaml"``, ``"json"``, or ``"toml"``.
            When omitted, format is detected from the file extension.
        required: If True, raises FileNotFoundError if the file is missing.
            If False, silently returns an empty config. Defaults to True.
    """

    def __init__(
        self, path: str, watch: bool = False, fmt: str | None = None, required: bool = True
    ):
        self._path = path
        self._watch = watch
        self._fmt = fmt
        self._required = required

    def read(self) -> dict:
        from layer.solidify import _read_file

        try:
            return _read_file(self._path, fmt=self._fmt)
        except FileNotFoundError:
            if not self._required:
                return {}
            raise

    @property
    def source_name(self) -> str:
        return f"file:{self._path}"

    @property
    def watchable(self) -> bool:
        return self._watch
