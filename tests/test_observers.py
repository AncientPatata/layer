"""Tests for BasePipelineObserver, LoggerObserver, and pipeline observer integration."""

import logging


from layer import layerclass, field, ConfigPipeline, BasePipelineObserver, LoggerObserver
from layer.providers.base import BaseProvider


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


class DictProvider(BaseProvider):
    def __init__(self, data, name="dict"):
        self._data = data
        self._name = name

    def read(self):
        return dict(self._data)

    @property
    def source_name(self):
        return self._name


class MutableDictProvider(BaseProvider):
    def __init__(self, data, name="mutable"):
        self.data = data
        self._name = name

    def read(self):
        return dict(self.data)

    @property
    def source_name(self):
        return self._name


@layerclass
class ObsConfig:
    host: str = field(str, default="localhost")
    port: int = field(int, default=5000)


# ---------------------------------------------------------------------------
# BasePipelineObserver default no-op behaviour
# ---------------------------------------------------------------------------


class TestBasePipelineObserver:
    def test_all_methods_are_noop(self):
        """BasePipelineObserver methods must not raise and return None."""
        obs = BasePipelineObserver()
        assert obs.on_provider_read("p", {}) is None
        assert obs.on_coercion_error("f", "v", int, ValueError()) is None
        assert obs.on_layer_merged("p", {}) is None
        assert obs.on_hot_reload_triggered([]) is None
        assert obs.on_hot_reload_locked("field") is None

    def test_subclass_can_override_selectively(self):
        events = []

        class Partial(BasePipelineObserver):
            def on_provider_read(self, provider_name, data):
                events.append(("read", provider_name))

        obs = Partial()
        obs.on_provider_read("p", {})
        obs.on_layer_merged("p", {})  # no-op, no crash
        assert events == [("read", "p")]


# ---------------------------------------------------------------------------
# LoggerObserver
# ---------------------------------------------------------------------------


class TestLoggerObserver:
    def test_on_provider_read_logs_debug(self, caplog):
        obs = LoggerObserver(logging.getLogger("test"))
        with caplog.at_level(logging.DEBUG):
            obs.on_provider_read("file:config.yml", {"host": "x", "port": "8080"})
        assert any("file:config.yml" in m for m in caplog.messages)
        assert any("2" in m for m in caplog.messages)  # 2 key(s)

    def test_on_layer_merged_logs_debug(self, caplog):
        obs = LoggerObserver(logging.getLogger("test"))
        with caplog.at_level(logging.DEBUG):
            obs.on_layer_merged("env:APP_*", {"port": "APPEND"})
        assert any("env:APP_*" in m for m in caplog.messages)

    def test_on_hot_reload_triggered_logs_info(self, caplog):
        obs = LoggerObserver(logging.getLogger("test"))
        diffs = [{"field": "host", "old_value": "a", "new_value": "b"}]
        with caplog.at_level(logging.INFO):
            obs.on_hot_reload_triggered(diffs)
        assert any("host" in m for m in caplog.messages)

    def test_on_hot_reload_locked_logs_warning(self, caplog):
        obs = LoggerObserver(logging.getLogger("test"))
        with caplog.at_level(logging.WARNING):
            obs.on_hot_reload_locked("api_key")
        assert any("api_key" in m for m in caplog.messages)

    def test_on_coercion_error_logs_warning(self, caplog):
        obs = LoggerObserver(logging.getLogger("test"))
        with caplog.at_level(logging.WARNING):
            obs.on_coercion_error("port", "bad", int, ValueError("not an int"))
        assert any("port" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Pipeline observer integration
# ---------------------------------------------------------------------------


class TestPipelineWithObserver:
    def test_observer_receives_provider_read(self):
        events = []

        class Spy(BasePipelineObserver):
            def on_provider_read(self, provider_name, data):
                events.append(provider_name)

        provider = DictProvider({"host": "obs.example.com"}, name="test-dict")
        pipeline = ConfigPipeline(ObsConfig, observer=Spy()).add_provider(provider)
        pipeline.load()

        assert "test-dict" in events

    def test_observer_receives_layer_merged(self):
        events = []

        class Spy(BasePipelineObserver):
            def on_layer_merged(self, provider_name, rules_applied):
                events.append((provider_name, rules_applied))

        provider = DictProvider({"host": "x"}, name="p1")
        pipeline = ConfigPipeline(ObsConfig, observer=Spy()).add_provider(provider)
        pipeline.load()

        assert len(events) == 1
        assert events[0][0] == "p1"

    def test_logger_kwarg_creates_logger_observer(self, caplog):
        provider = DictProvider({"host": "logged.example.com"}, name="file:cfg.yml")
        pipeline = ConfigPipeline(
            ObsConfig, logger=logging.getLogger("pipeline_test")
        ).add_provider(provider)
        with caplog.at_level(logging.DEBUG):
            pipeline.load()
        assert any("file:cfg.yml" in m for m in caplog.messages)

    def test_observer_fires_hot_reload_triggered(self):
        events = []

        class Spy(BasePipelineObserver):
            def on_hot_reload_triggered(self, diffs):
                events.extend(diffs)

        provider = MutableDictProvider({"host": "v1", "port": 5000})
        pipeline = ConfigPipeline(ObsConfig, observer=Spy()).add_provider(provider)
        pipeline.load()

        provider.data["host"] = "v2"
        pipeline._reload()

        assert any(d["field"] == "host" for d in events)

    def test_observer_fires_hot_reload_locked(self):
        from layer import field as layer_field

        locked_events = []

        class Spy(BasePipelineObserver):
            def on_hot_reload_locked(self, field_name):
                locked_events.append(field_name)

        @layerclass
        class LockConfig:
            log_level: str = layer_field(str, default="INFO")
            host: str = layer_field(str, default="localhost", reloadable=False)

        provider = MutableDictProvider({"host": "original", "log_level": "INFO"})
        pipeline = ConfigPipeline(LockConfig, observer=Spy()).add_provider(provider)
        pipeline.load()

        provider.data["host"] = "changed"
        pipeline._reload()

        assert "host" in locked_events

    def test_no_observer_does_not_raise(self):
        """Pipeline without observer should operate normally."""
        provider = DictProvider({"host": "plain"})
        pipeline = ConfigPipeline(ObsConfig).add_provider(provider)
        config = pipeline.load()
        assert config.host == "plain"
