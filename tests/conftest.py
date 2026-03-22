import pytest

from layer import field, layerclass, one_of, require


@layerclass
class TlsConfig:
    ca: str = field(str, description="CA certificate path", default=None)
    cert: str = field(str, description="Client certificate path", default=None)
    key: str = field(str, description="Client key path", default=None)


@layerclass
class AppConfig:
    endpoint: str = field(str, cluster=[require], description="Cluster endpoint")
    tls: TlsConfig = field(TlsConfig, description="TLS configuration", default=None)
    output: str = field(str, common=[one_of("json", "yaml", "table")], default="json")


@layerclass
class FileConfig:
    host: str = field(str, default="localhost")
    port: int = field(int, default=5000)


@pytest.fixture
def app_config():
    return AppConfig()


@pytest.fixture
def file_config():
    return FileConfig()
