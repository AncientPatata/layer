"""Tests for @computed_field — dynamic read-only fields integrated into to_dict/explain."""

import pytest
from layer import layerclass, field, computed_field


# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------


@layerclass
class TimeoutConfig:
    timeout_base: int = field(int, default=10)
    retry_count: int = field(int, default=3)

    @computed_field
    def total_timeout(self) -> int:
        return self.timeout_base * self.retry_count


@layerclass
class GreeterConfig:
    first_name: str = field(str, default="World")
    last_name: str = field(str, default="")

    @computed_field
    def greeting(self) -> str:
        """Friendly greeting message."""
        return f"Hello, {self.first_name}!"

    @computed_field
    def full_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Dynamic evaluation
# ---------------------------------------------------------------------------


class TestComputedFieldEvaluation:
    def test_evaluates_dynamically(self):
        c = TimeoutConfig()
        assert c.total_timeout == 30  # 10 * 3

    def test_updates_when_dependency_changes(self):
        c = TimeoutConfig()
        c.timeout_base = 5
        assert c.total_timeout == 15  # 5 * 3

    def test_multiple_computed_fields(self):
        c = GreeterConfig()
        c.first_name = "Alice"
        c.last_name = "Smith"
        assert c.greeting == "Hello, Alice!"
        assert c.full_name == "Alice Smith"

    def test_computed_with_empty_dependency(self):
        c = GreeterConfig()
        c.last_name = ""
        assert c.full_name == "World"  # last_name excluded when empty


# ---------------------------------------------------------------------------
# Mutation prevention
# ---------------------------------------------------------------------------


class TestComputedFieldMutation:
    def test_direct_assignment_raises(self):
        c = TimeoutConfig()
        with pytest.raises(AttributeError, match="computed"):
            c.total_timeout = 999

    def test_not_in_field_defs(self):
        assert "total_timeout" not in TimeoutConfig._field_defs

    def test_computed_fields_registered(self):
        assert "total_timeout" in TimeoutConfig._computed_fields


# ---------------------------------------------------------------------------
# to_dict integration
# ---------------------------------------------------------------------------


class TestComputedFieldToDict:
    def test_included_in_to_dict(self):
        c = TimeoutConfig()
        d = c.to_dict()
        assert "total_timeout" in d
        assert d["total_timeout"] == 30

    def test_reflects_current_values(self):
        c = TimeoutConfig()
        c.retry_count = 5
        assert c.to_dict()["total_timeout"] == 50

    def test_multiple_computed_in_to_dict(self):
        c = GreeterConfig()
        d = c.to_dict()
        assert "greeting" in d
        assert "full_name" in d

    def test_regular_fields_still_present(self):
        c = TimeoutConfig()
        d = c.to_dict()
        assert "timeout_base" in d
        assert "retry_count" in d


# ---------------------------------------------------------------------------
# explain() integration
# ---------------------------------------------------------------------------


class TestComputedFieldExplain:
    def test_included_in_explain(self):
        c = TimeoutConfig()
        info = c.explain()
        names = [e["field"] for e in info]
        assert "total_timeout" in names

    def test_source_is_computed(self):
        c = TimeoutConfig()
        info = c.explain()
        entry = next(e for e in info if e["field"] == "total_timeout")
        assert entry["source"] == "computed"

    def test_value_is_evaluated(self):
        c = TimeoutConfig()
        c.timeout_base = 7
        info = c.explain()
        entry = next(e for e in info if e["field"] == "total_timeout")
        assert entry["value"] == 21

    def test_description_from_docstring(self):
        c = GreeterConfig()
        info = c.explain()
        entry = next(e for e in info if e["field"] == "greeting")
        assert entry["description"] == "Friendly greeting message."

    def test_type_from_return_annotation(self):
        c = TimeoutConfig()
        info = c.explain()
        entry = next(e for e in info if e["field"] == "total_timeout")
        assert entry["type"] == "int"
