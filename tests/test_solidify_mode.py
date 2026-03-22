"""Tests for SolidifyMode — LAX, STANDARD, and STRICT strictness levels."""

import pytest

from layer import (
    ConfigPipeline,
    SolidifyMode,
    field,
    layerclass,
    solidify,
    solidify_file,
)
from layer.exceptions import CoercionError, StructureError
from layer.providers.base import BaseProvider


@layerclass
class ModeConfig:
    port: int = field(int, default=5000)
    host: str = field(str, default="localhost")


class DictProvider(BaseProvider):
    def __init__(self, data):
        self._data = data

    def read(self):
        return dict(self._data)

    @property
    def source_name(self):
        return "dict"


# ---------------------------------------------------------------------------
# LAX mode
# ---------------------------------------------------------------------------


class TestLaxMode:
    def test_ignores_unknown_keys(self):
        c = solidify(
            {"port": 8080, "unknown_key": "ignored"},
            ModeConfig,
            mode=SolidifyMode.LAX,
        )
        assert c.port == 8080

    def test_swallows_coercion_errors(self):
        # "notanumber" can't be coerced to int — LAX leaves it as-is
        c = solidify({"port": "notanumber"}, ModeConfig, mode=SolidifyMode.LAX)
        assert c.port == "notanumber"

    def test_valid_coercion_still_works(self):
        c = solidify({"port": "9090"}, ModeConfig, mode=SolidifyMode.LAX)
        assert c.port == 9090


# ---------------------------------------------------------------------------
# STANDARD mode
# ---------------------------------------------------------------------------


class TestStandardMode:
    def test_ignores_unknown_keys(self):
        c = solidify(
            {"port": 8080, "extra": "ok"},
            ModeConfig,
            mode=SolidifyMode.STANDARD,
        )
        assert c.port == 8080

    def test_raises_on_coercion_error(self):
        with pytest.raises((CoercionError, ValueError, TypeError)):
            solidify({"port": "notanumber"}, ModeConfig, mode=SolidifyMode.STANDARD)

    def test_valid_coercion_succeeds(self):
        c = solidify({"port": "7070"}, ModeConfig, mode=SolidifyMode.STANDARD)
        assert c.port == 7070


# ---------------------------------------------------------------------------
# STRICT mode
# ---------------------------------------------------------------------------


class TestStrictMode:
    def test_raises_on_unknown_key(self):
        with pytest.raises(StructureError):
            solidify(
                {"port": 8080, "unknown_key": "bad"},
                ModeConfig,
                mode=SolidifyMode.STRICT,
            )

    def test_no_coercion_string_stays_string(self):
        # STRICT disables coercion — string stays as string
        c = solidify({"port": "8080"}, ModeConfig, mode=SolidifyMode.STRICT)
        assert c.port == "8080"
        assert isinstance(c.port, str)

    def test_correct_type_passes_through(self):
        c = solidify({"port": 9090}, ModeConfig, mode=SolidifyMode.STRICT)
        assert c.port == 9090
        assert isinstance(c.port, int)

    def test_known_keys_accepted(self):
        c = solidify({"port": 1234, "host": "prod"}, ModeConfig, mode=SolidifyMode.STRICT)
        assert c.host == "prod"


# ---------------------------------------------------------------------------
# solidify_file with mode
# ---------------------------------------------------------------------------


class TestSolidifyFileMode:
    def test_strict_raises_on_unknown_key_in_file(self, tmp_path):
        import yaml

        path = str(tmp_path / "config.yml")
        with open(path, "w") as f:
            yaml.dump({"port": 8080, "unknown_field": "bad"}, f)

        with pytest.raises(StructureError):
            solidify_file(path, ModeConfig, mode=SolidifyMode.STRICT)

    def test_lax_ignores_unknown_key_in_file(self, tmp_path):
        import yaml

        path = str(tmp_path / "config.yml")
        with open(path, "w") as f:
            yaml.dump({"port": 8080, "unknown_field": "ignored"}, f)

        c = solidify_file(path, ModeConfig, mode=SolidifyMode.LAX)
        assert c.port == 8080


# ---------------------------------------------------------------------------
# ConfigPipeline with mode
# ---------------------------------------------------------------------------


class TestPipelineMode:
    def test_pipeline_strict_raises_on_unknown_key(self):
        provider = DictProvider({"port": 8080, "bad_key": "oops"})
        pipeline = ConfigPipeline(ModeConfig, mode=SolidifyMode.STRICT).add_provider(provider)
        with pytest.raises(StructureError):
            pipeline.load()

    def test_pipeline_lax_ignores_unknown_key(self):
        provider = DictProvider({"port": 8080, "bad_key": "ignored"})
        pipeline = ConfigPipeline(ModeConfig, mode=SolidifyMode.LAX).add_provider(provider)
        config = pipeline.load()
        assert config.port == 8080

    def test_pipeline_default_mode_is_none(self):
        pipeline = ConfigPipeline(ModeConfig)
        assert pipeline._mode is None


# ---------------------------------------------------------------------------
# Backward compatibility — legacy strict/coerce kwargs
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_legacy_strict_kwarg_still_works(self):
        with pytest.raises(StructureError):
            solidify(
                {"port": 8080, "unknown": "bad"},
                ModeConfig,
                strict=True,
            )

    def test_legacy_coerce_false_still_works(self):
        c = solidify({"port": "8080"}, ModeConfig, coerce=False)
        assert c.port == "8080"
        assert isinstance(c.port, str)

    def test_mode_overrides_strict_kwarg(self):
        # strict=True but mode=LAX → LAX wins, no error
        c = solidify(
            {"port": 8080, "unknown": "ok"},
            ModeConfig,
            strict=True,
            mode=SolidifyMode.LAX,
        )
        assert c.port == 8080
