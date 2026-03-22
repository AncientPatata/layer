"""Tests for nested @layerclass config objects."""

from layer import solidify, solidify_file, write_file
from layer.core import _is_layerclass
from conftest import AppConfig


class TestNestedDefaults:
    def test_nested_field_is_layerclass(self, app_config):
        assert _is_layerclass(app_config.tls)

    def test_nested_defaults_are_none(self, app_config):
        assert app_config.tls.ca is None
        assert app_config.tls.cert is None
        assert app_config.tls.key is None


class TestNestedSolidify:
    def test_from_dict(self):
        data = {
            "endpoint": "http://localhost:5001",
            "tls": {"ca": "/etc/ssl/ca.pem", "cert": "/etc/ssl/cert.pem"},
            "output": "yaml",
        }
        c = solidify(data, AppConfig, source="config.yml")
        assert c.endpoint == "http://localhost:5001"
        assert c.tls.ca == "/etc/ssl/ca.pem"
        assert c.tls.cert == "/etc/ssl/cert.pem"
        assert c.tls.key is None

    def test_to_dict_recurses(self, app_config):
        app_config.endpoint = "http://test"
        app_config.tls.ca = "/path/ca"
        d = app_config.to_dict()
        assert isinstance(d["tls"], dict)
        assert d["tls"]["ca"] == "/path/ca"


class TestNestedLayering:
    def test_merges_recursively(self):
        base = AppConfig()
        base.endpoint = "http://base"
        base.tls.ca = "/base/ca"
        overlay = solidify(
            {"tls": {"cert": "/overlay/cert"}}, AppConfig, source="overlay"
        )
        base.layer(overlay)
        assert base.tls.ca == "/base/ca"
        assert base.tls.cert == "/overlay/cert"

    def test_nested_source_history_is_snapshot(self):
        """Source history entry for a nested config must be frozen at the time
        of the layer(), not a live reference that mutates afterwards."""
        base = AppConfig()
        base.tls.ca = "/original/ca"
        overlay = solidify({"tls": {"cert": "/new/cert"}}, AppConfig, source="overlay")
        base.layer(overlay)

        # The source history for 'tls' should reflect the state AT layer time
        tls_history = base._sources["tls"]
        snapshot = tls_history.entries[-1].value

        # Now mutate the live tls config
        base.tls.ca = "/mutated/ca"

        # The snapshot must NOT reflect the mutation
        assert snapshot.ca != "/mutated/ca"


class TestNestedValidation:
    def test_required_field_caught(self, app_config):
        result = app_config.validate(["cluster"])
        assert not result.is_valid
        assert any("endpoint" in e.field for e in result.errors)


class TestNestedFileIO:
    def test_yaml_roundtrip(self, tmp_path, app_config):
        app_config.endpoint = "http://test"
        app_config.tls.ca = "/ca"
        app_config.tls.cert = "/cert"
        path = str(tmp_path / "app.yml")
        write_file(app_config, path)
        loaded = solidify_file(path, AppConfig, source="file")
        assert loaded.endpoint == "http://test"
        assert loaded.tls.ca == "/ca"
        assert loaded.tls.cert == "/cert"


class TestNestedCopy:
    def test_deep_copy(self, app_config):
        app_config.tls.ca = "/original"
        copy = app_config.copy()
        copy.tls.ca = "/changed"
        assert app_config.tls.ca == "/original"
