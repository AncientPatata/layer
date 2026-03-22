"""Tests for ConfigPipeline — orchestration, hot-reload, reactors, and thread safety."""

import threading
import pytest

from layer import ConfigPipeline
from layer.providers import BaseProvider, FileProvider
from conftest import AppConfig, FileConfig


# ---------------------------------------------------------------------------
# Test helper: DictProvider
# ---------------------------------------------------------------------------


class DictProvider(BaseProvider):
    """Simple in-memory provider for testing."""

    def __init__(self, data: dict, name: str = "dict"):
        self._data = data
        self._name = name

    def read(self) -> dict:
        return dict(self._data)

    @property
    def source_name(self) -> str:
        return self._name


# ---------------------------------------------------------------------------
# MutableDictProvider — for simulating changes during reload
# ---------------------------------------------------------------------------


class MutableDictProvider(BaseProvider):
    """Provider whose data can be changed between reads, for reload testing."""

    def __init__(self, data: dict, name: str = "mutable"):
        self.data = data
        self._name = name

    def read(self) -> dict:
        return dict(self.data)

    @property
    def source_name(self) -> str:
        return self._name


# ---------------------------------------------------------------------------
# Pipeline basics
# ---------------------------------------------------------------------------


class TestPipelineLoad:
    def test_load_single_provider(self):
        pipeline = ConfigPipeline(FileConfig).add_provider(
            DictProvider({"host": "example.com", "port": 9090})
        )
        config = pipeline.load()
        assert config.host == "example.com"
        assert config.port == 9090

    def test_load_layers_in_order(self):
        pipeline = (
            ConfigPipeline(FileConfig)
            .add_provider(DictProvider({"host": "first", "port": 1111}))
            .add_provider(DictProvider({"host": "second"}))
        )
        config = pipeline.load()
        assert config.host == "second"
        assert config.port == 1111  # Not overridden by second provider

    def test_method_chaining(self):
        pipeline = ConfigPipeline(FileConfig)
        result = pipeline.add_provider(DictProvider({}))
        assert result is pipeline

    def test_config_property(self):
        pipeline = ConfigPipeline(FileConfig)
        config = pipeline.config
        assert config is not None
        assert hasattr(config, "host")

    def test_load_freezes_config(self):
        pipeline = ConfigPipeline(FileConfig).add_provider(
            DictProvider({"host": "frozen.example.com"})
        )
        config = pipeline.load()
        assert config.frozen
        with pytest.raises(AttributeError):
            config.host = "changed"

    def test_accepts_class(self):
        pipeline = ConfigPipeline(FileConfig)
        config = pipeline.load()
        assert isinstance(config, FileConfig)

    def test_accepts_instance(self):
        instance = FileConfig()
        instance.host = "pre-set"
        pipeline = ConfigPipeline(instance).add_provider(DictProvider({"port": 8080}))
        config = pipeline.load()
        assert config.host == "pre-set"
        assert config.port == 8080
        assert config is instance

    def test_load_with_file_provider(self, tmp_path):
        import yaml

        path = str(tmp_path / "config.yml")
        with open(path, "w") as f:
            yaml.dump({"host": "file.example.com", "port": 3000}, f)

        pipeline = ConfigPipeline(FileConfig).add_provider(FileProvider(path))
        config = pipeline.load()
        assert config.host == "file.example.com"
        assert config.port == 3000

    def test_empty_provider_skipped(self):
        pipeline = (
            ConfigPipeline(FileConfig)
            .add_provider(DictProvider({}))
            .add_provider(DictProvider({"host": "after-empty"}))
        )
        config = pipeline.load()
        assert config.host == "after-empty"

    def test_load_with_nested_config(self):
        pipeline = ConfigPipeline(AppConfig).add_provider(
            DictProvider(
                {
                    "endpoint": "http://test",
                    "tls": {"ca": "/ca.pem", "cert": "/cert.pem"},
                }
            )
        )
        config = pipeline.load()
        assert config.endpoint == "http://test"
        assert config.tls.ca == "/ca.pem"
        assert config.tls.cert == "/cert.pem"


# ---------------------------------------------------------------------------
# Hot-reload
# ---------------------------------------------------------------------------


class TestPipelineReload:
    def test_reload_detects_changes(self):
        provider = MutableDictProvider({"host": "original", "port": 5000})
        pipeline = ConfigPipeline(FileConfig).add_provider(provider)
        pipeline.load()

        provider.data["host"] = "updated"
        pipeline._reload()
        assert pipeline.config.host == "updated"

    def test_reload_fires_reactor(self):
        provider = MutableDictProvider({"host": "original", "port": 5000})
        calls = []

        def reactor(field_path, old, new, shadow):
            calls.append({"field": field_path, "old": old, "new": new})

        pipeline = (
            ConfigPipeline(FileConfig).add_provider(provider).on_change("host", reactor)
        )
        pipeline.load()

        provider.data["host"] = "changed"
        pipeline._reload()

        assert len(calls) == 1
        assert calls[0]["field"] == "host"
        assert calls[0]["old"] == "original"
        assert calls[0]["new"] == "changed"

    def test_reload_default_mutator_applies_changes(self):
        provider = MutableDictProvider({"host": "v1", "port": 5000})
        pipeline = ConfigPipeline(FileConfig).add_provider(provider)
        config = pipeline.load()

        assert config.host == "v1"
        provider.data["host"] = "v2"
        pipeline._reload()
        assert config.host == "v2"
        assert config.frozen

    def test_reload_custom_mutator(self):
        provider = MutableDictProvider({"host": "v1", "port": 5000})
        mutator_calls = []

        def custom_mutator(field_path, old, new, shadow):
            mutator_calls.append(field_path)

        pipeline = (
            ConfigPipeline(FileConfig)
            .add_provider(provider)
            .on_change("*", custom_mutator)
        )
        pipeline.load()

        provider.data["host"] = "v2"
        pipeline._reload()

        # Custom mutator was called instead of default
        assert "host" in mutator_calls
        # Default mutator did NOT run — config still has old value
        # (custom mutator didn't actually set anything)
        # The frozen config can't be mutated without unfreezing,
        # so host remains "v1"

    def test_reload_no_diff_no_callbacks(self):
        provider = MutableDictProvider({"host": "stable", "port": 5000})
        calls = []

        pipeline = (
            ConfigPipeline(FileConfig)
            .add_provider(provider)
            .on_change("host", lambda *a: calls.append(1))
        )
        pipeline.load()

        # No changes — reload should be a no-op
        pipeline._reload()
        assert calls == []

    def test_reload_multiple_reactors_same_field(self):
        provider = MutableDictProvider({"host": "v1", "port": 5000})
        calls_a = []
        calls_b = []

        pipeline = (
            ConfigPipeline(FileConfig)
            .add_provider(provider)
            .on_change("host", lambda *a: calls_a.append(1))
            .on_change("host", lambda *a: calls_b.append(1))
        )
        pipeline.load()

        provider.data["host"] = "v2"
        pipeline._reload()

        assert len(calls_a) == 1
        assert len(calls_b) == 1

    def test_reactor_receives_shadow_config(self):
        provider = MutableDictProvider({"host": "v1", "port": 5000})
        shadows = []

        def reactor(field_path, old, new, shadow):
            shadows.append(shadow)

        pipeline = (
            ConfigPipeline(FileConfig).add_provider(provider).on_change("host", reactor)
        )
        pipeline.load()

        provider.data["host"] = "v2"
        provider.data["port"] = 9999
        pipeline._reload()

        assert len(shadows) == 1
        assert shadows[0].host == "v2"
        assert shadows[0].port == 9999


# ---------------------------------------------------------------------------
# _unfreeze_deep
# ---------------------------------------------------------------------------


class TestUnfreezeDeep:
    def test_unfreezes_top_level(self):
        c = FileConfig()
        c.freeze()
        assert c.frozen
        c._unfreeze_deep()
        assert not c.frozen

    def test_unfreezes_nested(self):
        c = AppConfig()
        c.freeze()
        assert c.frozen
        assert c.tls.frozen
        c._unfreeze_deep()
        assert not c.frozen
        assert not c.tls.frozen

    def test_allows_mutation_after_unfreeze(self):
        c = AppConfig()
        c.endpoint = "http://test"
        c.freeze()
        c._unfreeze_deep()
        c.endpoint = "http://changed"
        assert c.endpoint == "http://changed"
        c.tls.ca = "/new/ca"
        assert c.tls.ca == "/new/ca"


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestPipelineThreadSafety:
    def test_concurrent_reloads(self):
        provider = MutableDictProvider({"host": "start", "port": 5000})
        pipeline = ConfigPipeline(FileConfig).add_provider(provider)
        pipeline.load()

        errors = []

        def reload_worker(value):
            try:
                provider.data["host"] = value
                pipeline._reload()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            t = threading.Thread(target=reload_worker, args=(f"host-{i}",))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # Config should be frozen and consistent
        assert pipeline.config.frozen
        assert isinstance(pipeline.config.host, str)


# ---------------------------------------------------------------------------
# on_change chaining
# ---------------------------------------------------------------------------


class TestOnChangeChaining:
    def test_on_change_returns_self(self):
        pipeline = ConfigPipeline(FileConfig)
        result = pipeline.on_change("host", lambda *a: None)
        assert result is pipeline

    def test_wildcard_sets_mutator(self):
        pipeline = ConfigPipeline(FileConfig)

        def noop(*a):
            pass

        pipeline.on_change("*", noop)
        assert pipeline._mutator is noop


# ---------------------------------------------------------------------------
# reloadable=False field locking
# ---------------------------------------------------------------------------


class TestReloadableLocking:
    def _make_locked_config(self):
        """Config with a reloadable=False field."""
        from layer import layer_obj, field

        @layer_obj
        class LockConfig:
            log_level: str = field(str, default="INFO")
            host: str = field(str, default="localhost", reloadable=False)

        return LockConfig

    def test_reloadable_false_skips_field_on_reload(self):
        LockConfig = self._make_locked_config()
        provider = MutableDictProvider({"host": "original", "log_level": "INFO"})
        pipeline = ConfigPipeline(LockConfig).add_provider(provider)
        pipeline.load()

        provider.data["host"] = "changed"
        pipeline._reload()

        # host has reloadable=False — should not be updated
        assert pipeline.config.host == "original"

    def test_reloadable_true_still_mutates(self):
        LockConfig = self._make_locked_config()
        provider = MutableDictProvider({"host": "original", "log_level": "INFO"})
        pipeline = ConfigPipeline(LockConfig).add_provider(provider)
        pipeline.load()

        provider.data["log_level"] = "DEBUG"
        pipeline._reload()

        # log_level is reloadable=True (default) — should update
        assert pipeline.config.log_level == "DEBUG"

    def test_reloadable_false_emits_warning(self, caplog):
        import logging

        LockConfig = self._make_locked_config()
        provider = MutableDictProvider({"host": "original", "log_level": "INFO"})
        pipeline = ConfigPipeline(LockConfig).add_provider(provider)
        pipeline.load()

        provider.data["host"] = "changed"
        with caplog.at_level(logging.WARNING):
            pipeline._reload()

        assert any("host" in msg for msg in caplog.messages)

    def test_reloadable_false_nested_field(self):
        from layer import layer_obj, field

        @layer_obj
        class TlsConf:
            cert: str = field(str, default=None, reloadable=False)
            ca: str = field(str, default=None)

        @layer_obj
        class AppConf:
            tls: TlsConf = field(TlsConf, default=None)

        provider = MutableDictProvider(
            {"tls": {"cert": "/original/cert", "ca": "/original/ca"}}
        )
        pipeline = ConfigPipeline(AppConf).add_provider(provider)
        pipeline.load()

        provider.data["tls"]["cert"] = "/changed/cert"
        provider.data["tls"]["ca"] = "/changed/ca"
        pipeline._reload()

        # cert has reloadable=False — not updated
        assert pipeline.config.tls.cert == "/original/cert"
        # ca is reloadable=True (default) — updated
        assert pipeline.config.tls.ca == "/changed/ca"
