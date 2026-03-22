"""Tests for polish features: layerclass rename, pipeline validate, layering rules, exceptions."""

import pytest
from layer import (
    layerclass,
    layer_obj,
    field,
    ConfigPipeline,
    LayerRule,
    ValidationError,
    MissingDependencyError,
    HotReloadError,
    InterpolationCycleError,
    InterpolationError,
)
from layer.providers.base import BaseProvider


# ---------------------------------------------------------------------------
# Shared helpers
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


# ---------------------------------------------------------------------------
# @layerclass rename
# ---------------------------------------------------------------------------


class TestLayerclassRename:
    def test_layerclass_decorator_works(self):
        @layerclass
        class MyConf:
            host: str = field(str, default="localhost")

        c = MyConf()
        assert c.host == "localhost"

    def test_layer_obj_backward_compat_alias(self):
        """layer_obj must still work as a backward-compat alias."""

        @layer_obj
        class LegacyConf:
            port: int = field(int, default=9090)

        c = LegacyConf()
        assert c.port == 9090

    def test_layerclass_marker_set(self):
        @layerclass
        class Marked:
            x: int = field(int, default=1)

        assert hasattr(Marked, "_is_layerclass_marker")

    def test_layer_obj_marker_backward_compat(self):
        """_is_layer_obj_marker must still be present for backward compat."""

        @layerclass
        class Marked:
            x: int = field(int, default=1)

        assert hasattr(Marked, "_is_layer_obj_marker")

    def test_is_layerclass_helper(self):
        from layer.core import _is_layerclass

        @layerclass
        class C:
            x: int = field(int, default=1)

        assert _is_layerclass(C)
        assert _is_layerclass(C())
        assert not _is_layerclass(int)

    def test_layer_obj_alias_is_same_function(self):
        assert layer_obj is layerclass


# ---------------------------------------------------------------------------
# Pipeline validate() method
# ---------------------------------------------------------------------------


@layerclass
class ValidatedConfig:
    host: str = field(str, default="localhost")
    port: int = field(int, default=5432, server=[pytest.importorskip("layer").require])


class TestPipelineValidate:
    def test_validate_method_exists(self):
        pipeline = ConfigPipeline(ValidatedConfig).add_provider(DictProvider({}))
        pipeline.load()
        assert hasattr(pipeline, "validate")

    def test_validate_returns_validation_result(self):
        pipeline = ConfigPipeline(ValidatedConfig).add_provider(
            DictProvider({"host": "db.example.com", "port": 5432})
        )
        pipeline.load()
        result = pipeline.validate(["server"])
        assert hasattr(result, "errors")
        assert hasattr(result, "raise_if_invalid")

    def test_validate_passes_when_valid(self):
        pipeline = ConfigPipeline(ValidatedConfig).add_provider(
            DictProvider({"host": "db.example.com", "port": 5432})
        )
        pipeline.load()
        result = pipeline.validate(["server"])
        assert result.errors == []

    def test_load_does_not_run_validation(self):
        """load() must succeed even when required fields are missing."""

        @layerclass
        class StrictConf:
            token: str = field(str, default=None, server=[pytest.importorskip("layer").require])

        # No token provided — load() should NOT raise
        pipeline = ConfigPipeline(StrictConf).add_provider(DictProvider({}))
        config = pipeline.load()
        assert config.token is None


# ---------------------------------------------------------------------------
# Pipeline add_provider with rules
# ---------------------------------------------------------------------------


@layerclass
class RulesConfig:
    host: str = field(str, default="localhost")
    ports: list = field(list, default=None)
    tags: list = field(list, default=None)


class TestPipelineLayeringRules:
    def test_append_rule_merges_lists(self):
        pipeline = (
            ConfigPipeline(RulesConfig)
            .add_provider(DictProvider({"ports": [8080]}, name="base"))
            .add_provider(
                DictProvider({"ports": [9090]}, name="overlay"),
                rules={"ports": LayerRule.APPEND},
            )
        )
        config = pipeline.load()
        assert config.ports == [8080, 9090]

    def test_preserve_rule_keeps_base_value(self):
        pipeline = (
            ConfigPipeline(RulesConfig)
            .add_provider(DictProvider({"host": "base.host"}, name="base"))
            .add_provider(
                DictProvider({"host": "override.host"}, name="overlay"),
                rules={"host": LayerRule.PRESERVE},
            )
        )
        config = pipeline.load()
        assert config.host == "base.host"

    def test_override_rule_replaces_value(self):
        pipeline = (
            ConfigPipeline(RulesConfig)
            .add_provider(DictProvider({"host": "base.host"}))
            .add_provider(
                DictProvider({"host": "new.host"}),
                rules={"host": LayerRule.OVERRIDE},
            )
        )
        config = pipeline.load()
        assert config.host == "new.host"

    def test_no_rules_defaults_to_override(self):
        pipeline = (
            ConfigPipeline(RulesConfig)
            .add_provider(DictProvider({"host": "first"}))
            .add_provider(DictProvider({"host": "second"}))
        )
        config = pipeline.load()
        assert config.host == "second"


# ---------------------------------------------------------------------------
# Pipeline resolve() — interpolation during load
# ---------------------------------------------------------------------------


@layerclass
class InterpolConfig:
    base_url: str = field(str, default="example.com")
    api_url: str = field(str, default="https://${base_url}/api")


class TestPipelineResolve:
    def test_interpolation_resolved_after_load(self):
        pipeline = ConfigPipeline(InterpolConfig).add_provider(
            DictProvider({"base_url": "myservice.io"})
        )
        config = pipeline.load()
        assert config.api_url == "https://myservice.io/api"

    def test_interpolation_in_shadow_during_reload(self):
        from layer.providers.base import BaseProvider

        class MutableProv(BaseProvider):
            def __init__(self, data):
                self.data = data

            def read(self):
                return dict(self.data)

            @property
            def source_name(self):
                return "mutable"

        provider = MutableProv({"base_url": "v1.io"})
        pipeline = ConfigPipeline(InterpolConfig).add_provider(provider)
        pipeline.load()

        provider.data["base_url"] = "v2.io"
        pipeline._reload()

        assert pipeline.config.api_url == "https://v2.io/api"


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_validation_error_format(self):
        err = ValidationError("host", "must not be empty", "require", "server")
        msg = str(err)
        assert "[Category: server]" in msg
        assert "Field 'host'" in msg
        assert "rule 'require'" in msg
        assert "must not be empty" in msg

    def test_missing_dependency_error_is_config_error(self):
        from layer import ConfigError

        err = MissingDependencyError("boto3 not installed")
        assert isinstance(err, ConfigError)

    def test_hot_reload_error_is_config_error(self):
        from layer import ConfigError

        err = HotReloadError("reload failed")
        assert isinstance(err, ConfigError)

    def test_interpolation_cycle_error_is_interpolation_error(self):
        err = InterpolationCycleError("circular: a -> b -> a")
        assert isinstance(err, InterpolationError)

    def test_cycle_detected_in_interpolation(self):
        """Circular ${...} references should raise InterpolationCycleError."""

        @layerclass
        class CycleConf:
            a: str = field(str, default="${b}")
            b: str = field(str, default="${a}")

        c = CycleConf()
        # resolve() swallows InterpolationError internally but should not crash
        # The important thing is that cyclic detection raises InterpolationCycleError
        from layer.interpolation import resolve_value

        with pytest.raises(InterpolationCycleError):
            resolve_value("${a}", c)
