"""SSMProvider — reads config from AWS Systems Manager Parameter Store."""

from ..exceptions import MissingDependencyError
from .base import BaseProvider


class SSMProvider(BaseProvider):
    """Reads configuration from AWS SSM Parameter Store.

    Fetches all parameters under the given path prefix. Parameter names
    are converted to lowercase field names with the prefix stripped and
    slashes replaced by underscores.

    Requires boto3: pip install layer[aws]

    Args:
        path_prefix: SSM path prefix (e.g. "/prod/app/").
        region: AWS region name. Uses boto3 defaults if None.
    """

    def __init__(self, path_prefix: str, region: str = None):
        self._path_prefix = path_prefix.rstrip("/") + "/"
        self._region = region

    def read(self) -> dict:
        try:
            import boto3
        except ImportError:
            raise MissingDependencyError(
                "boto3 is required for SSMProvider: pip install layer[aws]"
            )
        kwargs = {}
        if self._region:
            kwargs["region_name"] = self._region
        client = boto3.client("ssm", **kwargs)
        result = {}
        paginator = client.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(Path=self._path_prefix, WithDecryption=True):
            for param in page["Parameters"]:
                key = param["Name"][len(self._path_prefix) :].replace("/", "_").lower()
                result[key] = param["Value"]
        return result

    @property
    def source_name(self) -> str:
        return f"ssm:{self._path_prefix}"
