"""Tests for diff(), freeze(), secret redaction, and to_dict() serialization."""

import dataclasses
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


# ---------------------------------------------------------------------------
# to_dict() with external model types
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Point:
    x: int
    y: int


@layer_obj
class PointConfig:
    location: Point = field(Point, default=None)
    name: str = field(str, default="default")


class TestToDictExternalModels:
    def test_dataclass_field_serialized_to_dict(self):
        c = PointConfig()
        c.location = Point(x=3, y=7)
        result = c.to_dict()
        assert isinstance(result["location"], dict)
        assert result["location"] == {"x": 3, "y": 7}

    def test_none_field_not_affected(self):
        c = PointConfig()
        # location defaults to None
        result = c.to_dict()
        assert result["location"] is None

    def test_plain_field_unaffected(self):
        c = PointConfig()
        c.name = "hello"
        result = c.to_dict()
        assert result["name"] == "hello"

    def test_dataclass_class_not_mistakenly_serialized(self):
        # A field whose *value* happens to be a dataclass class (not instance)
        # should not be passed to dataclasses.asdict()
        c = PointConfig()
        # Assign the class itself (edge case)
        object.__setattr__(c, "location", Point)
        result = c.to_dict()
        # Should return the class as-is, not raise
        assert result["location"] is Point

    def test_pydantic_field_serialized_to_dict(self):
        pytest.importorskip("pydantic", reason="pydantic not installed")
        from pydantic import BaseModel

        class Address(BaseModel):
            street: str
            city: str

        @layer_obj
        class AddrConfig:
            address: Address = field(Address, default=None)

        c = AddrConfig()
        c.address = Address(street="123 Main St", city="Anytown")
        result = c.to_dict()
        assert isinstance(result["address"], dict)
        assert result["address"]["city"] == "Anytown"
