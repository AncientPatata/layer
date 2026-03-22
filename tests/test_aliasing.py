"""Tests for field aliasing: alias, aliases, env, and to_dict(by_alias=True)."""

import pytest
from layer import layerclass, field, solidify, solidify_env
from layer.exceptions import StructureError


@layerclass
class AliasConfig:
    api_key: str = field(str, alias="apiKey", default=None)
    server_port: int = field(
        int, alias="server-port", aliases=["serverPort"], default=8080
    )
    user_name: str = field(str, default="admin")  # no alias — tests fallback behaviour


class TestSolidifyAlias:
    def test_alias_maps_to_field(self):
        c = solidify({"apiKey": "secret"}, AliasConfig)
        assert c.api_key == "secret"

    def test_canonical_name_still_works(self):
        c = solidify({"api_key": "secret"}, AliasConfig)
        assert c.api_key == "secret"

    def test_kebab_alias(self):
        c = solidify({"server-port": 9090}, AliasConfig)
        assert c.server_port == 9090

    def test_aliases_fallback(self):
        c = solidify({"serverPort": 8888}, AliasConfig)
        assert c.server_port == 8888

    def test_camelcase_alias_not_normalised(self):
        # "apiKey" must be matched as-is; normalising it to "apikey" would miss it
        c = solidify({"apiKey": "camel"}, AliasConfig)
        assert c.api_key == "camel"

    def test_field_without_alias_unchanged(self):
        c = solidify({"user_name": "bob"}, AliasConfig)
        assert c.user_name == "bob"

    def test_strict_rejects_unknown_key(self):
        with pytest.raises(StructureError):
            solidify({"unknownKey": "x"}, AliasConfig, strict=True)

    def test_strict_accepts_alias(self):
        # aliases must be considered known keys in strict mode
        c = solidify({"apiKey": "ok"}, AliasConfig, strict=True)
        assert c.api_key == "ok"


class TestSolidifyEnvField:
    def test_uses_fdef_env(self, monkeypatch):
        @layerclass
        class C:
            api_key: str = field(str, env="MY_CUSTOM_KEY", default=None)

        monkeypatch.setenv("MY_CUSTOM_KEY", "from-env")
        c = solidify_env("APP", C)
        assert c.api_key == "from-env"

    def test_fdef_env_takes_priority_over_prefix(self, monkeypatch):
        @layerclass
        class C:
            api_key: str = field(str, env="MY_CUSTOM_KEY", default=None)

        monkeypatch.setenv("APP_API_KEY", "should-be-ignored")
        monkeypatch.setenv("MY_CUSTOM_KEY", "from-env")
        c = solidify_env("APP", C)
        assert c.api_key == "from-env"

    def test_falls_back_to_prefix_when_env_absent(self, monkeypatch):
        @layerclass
        class C:
            api_key: str = field(str, default=None)

        monkeypatch.setenv("APP_API_KEY", "from-prefix")
        c = solidify_env("APP", C)
        assert c.api_key == "from-prefix"

    def test_missing_env_leaves_default(self, monkeypatch):
        @layerclass
        class C:
            api_key: str = field(str, env="NONEXISTENT_VAR", default="fallback")

        c = solidify_env("APP", C)
        assert c.api_key == "fallback"


class TestToDictByAlias:
    def test_by_alias_false_uses_field_name(self):
        c = AliasConfig()
        c.api_key = "secret"
        d = c.to_dict(by_alias=False)
        assert "api_key" in d
        assert "apiKey" not in d

    def test_by_alias_true_uses_alias(self):
        c = AliasConfig()
        c.api_key = "secret"
        d = c.to_dict(by_alias=True)
        assert d["apiKey"] == "secret"
        assert "api_key" not in d

    def test_by_alias_true_falls_back_to_field_name_without_alias(self):
        c = AliasConfig()
        d = c.to_dict(by_alias=True)
        # user_name has no alias — field name is used
        assert "user_name" in d

    def test_by_alias_default_is_false(self):
        c = AliasConfig()
        c.api_key = "x"
        d = c.to_dict()
        assert "api_key" in d
