"""Tests for diff(), freeze(), and secret redaction."""

import pytest
from layer import layer_obj, field
from conftest import AppConfig


@layer_obj
class SecretConfig:
    user: str = field(str, default="admin")
    password: str = field(str, secret=True, default="supersecret")


class TestDiff:
    def test_detects_changed_fields(self):
        a = AppConfig()
        a.endpoint = "http://a"
        b = AppConfig()
        b.endpoint = "http://b"
        diffs = a.diff(b)
        assert len(diffs) == 1
        assert diffs[0]["field"] == "endpoint"
        assert diffs[0]["old_value"] == "http://a"
        assert diffs[0]["new_value"] == "http://b"

    def test_empty_when_identical(self):
        assert AppConfig().diff(AppConfig()) == []

    def test_recurses_into_nested(self):
        a = AppConfig()
        a.tls.ca = "/old/ca"
        b = AppConfig()
        b.tls.ca = "/new/ca"
        diffs = a.diff(b)
        assert any(d["field"] == "tls.ca" for d in diffs)


class TestFreeze:
    def test_prevents_field_mutation(self):
        c = AppConfig()
        c.endpoint = "http://test"
        c.freeze()
        with pytest.raises(AttributeError):
            c.endpoint = "http://changed"

    def test_frozen_property_reflects_state(self):
        c = AppConfig()
        assert not c.frozen
        c.freeze()
        assert c.frozen

    def test_freezes_nested_configs(self):
        c = AppConfig()
        c.freeze()
        with pytest.raises(AttributeError):
            c.tls.ca = "/changed"


class TestSecretRedaction:
    def test_to_dict_redacts(self):
        c = SecretConfig()
        redacted = c.to_dict(redact=True)
        assert redacted["password"] == "***"
        assert redacted["user"] == "admin"

    def test_to_dict_plain_exposes_value(self):
        c = SecretConfig()
        assert c.to_dict(redact=False)["password"] == "supersecret"

    def test_explain_redacts(self):
        c = SecretConfig()
        info = c.explain(redact=True)
        pw = next(i for i in info if i["field"] == "password")
        assert pw["value"] == "***"
