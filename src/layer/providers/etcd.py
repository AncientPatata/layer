"""EtcdProvider — reads config from an etcd cluster."""

from ..exceptions import MissingDependencyError
from .base import BaseProvider


class EtcdProvider(BaseProvider):
    """Reads configuration from an etcd cluster.

    Fetches all keys under the given path prefix. Parameter names
    are converted to lowercase field names with the prefix stripped and
    slashes replaced by underscores.

    Requires etcd3: pip install layerconf[etcd]

    Args:
        prefix: Etcd path prefix (e.g. "/myapp/prod/").
        host: etcd host (default "localhost").
        port: etcd port (default 2379).
        **kwargs: Additional arguments passed to etcd3.client()
            (e.g., ca_cert, cert_key, cert_cert, timeout, user, password).
    """

    def __init__(self, prefix: str, host: str = "localhost", port: int = 2379, **kwargs):
        self._prefix = prefix.rstrip("/") + "/"
        self._host = host
        self._port = port
        self._client_kwargs = kwargs
        self._schema = None

    def bind_schema(self, schema: type) -> None:
        self._schema = schema

    def read(self) -> dict:
        try:
            import etcd3
        except ImportError:
            raise MissingDependencyError(
                "etcd3 is required for EtcdProvider: pip install layerconf[etcd]"
            )

        client = etcd3.client(host=self._host, port=self._port, **self._client_kwargs)
        pool = {}

        # get_prefix returns an iterator of (value, metadata) tuples.
        for value, metadata in client.get_prefix(self._prefix):
            key = metadata.key.decode("utf-8")
            val = value.decode("utf-8")

            # Keep the relative path (e.g., "database/port")
            relative_key = key[len(self._prefix) :]
            pool[relative_key] = val

        if self._schema:
            return self._resolve_schema(self._schema, "", pool)
        else:
            return self._resolve_flat(pool)

    def _resolve_schema(self, cls, prefix: str, pool: dict) -> dict:
        from ..solidify import _is_layer_obj_type

        result = {}

        # prefix is empty at the root, otherwise like "database/"
        for name, fdef in cls._field_defs.items():
            if _is_layer_obj_type(fdef.type_hint):
                sub_prefix = f"{prefix}{name}/"
                nested = self._resolve_schema(fdef.type_hint, sub_prefix, pool)
                if nested:
                    result[name] = nested
                continue

            # Target key is "database/port"
            target_key = f"{prefix}{name}"

            # Also allow fallback to the legacy flattened name if someone used that format in etcd
            # e.g., "database_port" instead of "database/port"
            legacy_key = target_key.replace("/", "_")

            if target_key in pool:
                result[name] = pool[target_key]
            elif legacy_key in pool:
                result[name] = pool[legacy_key]

        return result

    def _resolve_flat(self, pool: dict) -> dict:
        result = {}
        for k, v in pool.items():
            # Legacy fallback: convert "database/port" -> "database_port"
            result[k.replace("/", "_").lower()] = v
        return result

    @property
    def source_name(self) -> str:
        return f"etcd:{self._prefix}"
