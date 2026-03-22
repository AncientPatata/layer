"""DotEnvProvider — reads config from .env files via python-dotenv."""

from ..exceptions import MissingDependencyError
from .base import BaseProvider


class DotEnvProvider(BaseProvider):
    """Reads configuration from a .env file.

    Injects parsed variables into os.environ (without overwriting existing
    values), then returns an empty dict. This allows a subsequent EnvProvider
    in the pipeline to pick up the variables and handle prefix-stripping.

    Chain as: DotEnvProvider(".env") → EnvProvider(prefix="APP")

    Requires python-dotenv: pip install layer[dotenv]

    Args:
        path: Path to the .env file (default ".env").
    """

    def __init__(self, path: str = ".env"):
        self._path = path

    def read(self) -> dict:
        import os

        try:
            from dotenv import dotenv_values
        except ImportError:
            raise MissingDependencyError(
                "python-dotenv is required for DotEnvProvider: pip install layer[dotenv]"
            )
        env_vars = dotenv_values(self._path)
        for k, v in env_vars.items():
            if k not in os.environ and v is not None:
                os.environ[k] = v
        return {}

    @property
    def source_name(self) -> str:
        return f"dotenv:{self._path}"
