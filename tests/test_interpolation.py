"""Tests for variable interpolation and source history tracking."""

from layer import layerclass, field


@layerclass
class InterpolationConfig:
    host: str = field(str, default="localhost")
    port: int = field(int, default=8080)
    url: str = field(str, default="http://${host}:${port}/api")
    nested_url: str = field(str, default="${url}/v1")


class TestInterpolation:
    def test_resolves_variables(self):
        c = InterpolationConfig()
        c.resolve()
        assert c.url == "http://localhost:8080/api"

    def test_resolves_chained_references(self):
        c = InterpolationConfig()
        c.resolve()
        assert c.nested_url == "http://localhost:8080/api/v1"

    def test_custom_host_and_port(self):
        c = InterpolationConfig()
        c.host = "prod.example.com"
        c.port = 443
        c.resolve()
        assert c.url == "http://prod.example.com:443/api"


class TestSourceHistory:
    def test_tracks_latest_source(self, file_config):
        file_config.set("host", "first.com", source="init")
        file_config.set("host", "second.com", source="update")
        assert file_config.source_of("host") == "update"

    def test_records_all_entries(self, file_config):
        file_config.set("host", "first.com", source="init")
        file_config.set("host", "second.com", source="update")
        history = file_config.source_history_of("host")
        assert len(history) >= 2
        assert history[-1].source == "update"
        assert history[-1].value == "second.com"
