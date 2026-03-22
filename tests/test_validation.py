"""Tests for cross-field validators and layering rules."""

from layer import LayerRule, field, layerclass, requires_if


@layerclass
class CrossValidConfig:
    auth_type: str = field(str, default="none")
    token: str = field(str, default=None, auth=[requires_if("auth_type", "bearer")])


@layerclass
class MergeConfig:
    items: list = field(list, default=["a"])
    flags: dict = field(dict, default={"debug": True})


class TestCrossFieldValidation:
    def test_requires_if_fails_when_trigger_met(self):
        c = CrossValidConfig()
        c.auth_type = "bearer"
        assert not c.validate(["auth"]).is_valid

    def test_requires_if_passes_when_field_provided(self):
        c = CrossValidConfig()
        c.auth_type = "bearer"
        c.token = "abc-123"
        assert c.validate(["auth"]).is_valid

    def test_requires_if_skips_when_trigger_not_met(self):
        c = CrossValidConfig()
        c.auth_type = "none"
        assert c.validate(["auth"]).is_valid


class TestLayeringRules:
    def test_append_concatenates_lists(self):
        base = MergeConfig()
        base.set("items", ["a"], source="base")
        overlay = MergeConfig()
        overlay.set("items", ["b", "c"], source="overlay")
        base.layer(overlay, rules={"items": LayerRule.APPEND})
        assert base.items == ["a", "b", "c"]

    def test_merge_unions_dicts(self):
        base = MergeConfig()
        base.set("flags", {"debug": True, "verbose": False}, source="base")
        overlay = MergeConfig()
        overlay.set("flags", {"verbose": True}, source="overlay")
        base.layer(overlay, rules={"flags": LayerRule.MERGE})
        assert base.flags == {"debug": True, "verbose": True}

    def test_preserve_keeps_original_value(self):
        base = MergeConfig()
        base.set("items", ["original"], source="base")
        overlay = MergeConfig()
        overlay.set("items", ["new"], source="overlay")
        base.layer(overlay, rules={"items": LayerRule.PRESERVE})
        assert base.items == ["original"]

    def test_override_replaces_value(self):
        base = MergeConfig()
        base.set("items", ["old"], source="base")
        overlay = MergeConfig()
        overlay.set("items", ["new"], source="overlay")
        base.layer(overlay, rules={"items": LayerRule.OVERRIDE})
        assert base.items == ["new"]
