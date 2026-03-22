"""VaultProvider — reads config from HashiCorp Vault KV v2."""

import os

from ..exceptions import MissingDependencyError
from .base import BaseProvider


class VaultProvider(BaseProvider):
    """Reads configuration from HashiCorp Vault (KV v2 secrets engine).

    Falls back to VAULT_ADDR and VAULT_TOKEN environment variables if
    url/token are not provided explicitly.

    Requires hvac: pip install layer[vault]

    Args:
        secret_path: Path to the secret in Vault (e.g. "myapp/config").
        url: Vault server URL. Defaults to VAULT_ADDR or http://127.0.0.1:8200.
        token: Vault token. Defaults to VAULT_TOKEN env var.
        mount_point: KV v2 mount point (default "secret").
    """

    def __init__(
        self,
        secret_path: str,
        url: str = None,
        token: str = None,
        mount_point: str = "secret",
    ):
        self._secret_path = secret_path
        self._url = url
        self._token = token
        self._mount_point = mount_point

    def read(self) -> dict:
        try:
            import hvac
        except ImportError:
            raise MissingDependencyError(
                "hvac is required for VaultProvider: pip install layer[vault]"
            )
        url = self._url or os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
        token = self._token or os.environ.get("VAULT_TOKEN")
        client = hvac.Client(url=url, token=token)
        response = client.secrets.kv.v2.read_secret_version(
            path=self._secret_path, mount_point=self._mount_point
        )
        return response["data"]["data"]

    @property
    def source_name(self) -> str:
        return f"vault:{self._mount_point}/{self._secret_path}"
