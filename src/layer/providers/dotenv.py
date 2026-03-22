"""DotEnvProvider — reads config from .env files via python-dotenv."""

from .base import BaseProvider


class DotEnvProvider(BaseProvider):
    """Reads configuration from a .env file.

    Returns key-value pairs as a dict. Does NOT inject into os.environ —
    if you need env injection, chain DotEnvProvider before EnvProvider.

    Requires python-dotenv: pip install layer[dotenv]

    Args:
        path: Path to the .env file (default ".env").
    """

    def __init__(self, path: str = ".env"):
        self._path = path

    def read(self) -> dict:
        try:
            from dotenv import dotenv_values
        except ImportError:
            raise ImportError(
                "python-dotenv is required for DotEnvProvider: "
                "pip install layer[dotenv]"
            )
        return dict(dotenv_values(self._path))

    @property
    def source_name(self) -> str:
        return f"dotenv:{self._path}"
