"""Tests for solidify() type coercion and solidify_file() / write_file() serialization."""
import pytest
from layer import layer_obj, field, solidify, solidify_file, write_file
from conftest import FileConfig


@layer_obj
class CoerceConfig:
    port: int = field(int, default=5000)
    debug: bool = field(bool, default=False)
    rate: float = field(float, default=1.0)
    tags: list = field(list, default=None)
    labels: dict = field(dict, default=None)


class TestTypeCoercion:
    def test_str_to_int(self):
        c = solidify({"port": "8080"}, CoerceConfig)
        assert c.port == 8080
        assert isinstance(c.port, int)

    def test_str_to_bool_true(self):
        assert solidify({"debug": "true"}, CoerceConfig).debug is True

    def test_str_to_bool_false(self):
        assert solidify({"debug": "false"}, CoerceConfig).debug is False

    def test_str_to_float(self):
        c = solidify({"rate": "3.14"}, CoerceConfig)
        assert abs(c.rate - 3.14) < 0.001

    def test_str_to_list_comma_separated(self):
        assert solidify({"tags": "web, prod"}, CoerceConfig).tags == ["web", "prod"]

    def test_str_to_dict_key_value_pairs(self):
        c = solidify({"labels": "env=prod, tier=web"}, CoerceConfig)
        assert c.labels == {"env": "prod", "tier": "web"}

    def test_correct_type_unchanged(self):
        assert solidify({"port": 9090}, CoerceConfig).port == 9090

    def test_coerce_false_skips_conversion(self):
        c = solidify({"port": "8080"}, CoerceConfig, coerce=False)
        assert c.port == "8080"


class TestFileIO:
    def test_yaml_roundtrip(self, tmp_path):
        c = FileConfig()
        c.host = "prod.example.com"
        c.port = 9090
        path = str(tmp_path / "config.yml")
        write_file(c, path)
        loaded = solidify_file(path, FileConfig, source="test-file")
        assert loaded.host == "prod.example.com"
        assert loaded.port == 9090

    def test_json_roundtrip(self, tmp_path):
        c = FileConfig()
        c.host = "staging.example.com"
        path = str(tmp_path / "config.json")
        write_file(c, path)
        loaded = solidify_file(path, FileConfig)
        assert loaded.host == "staging.example.com"
