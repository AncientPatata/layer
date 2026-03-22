"""Tests for the advanced type resolution / coercion engine."""

import dataclasses
from typing import Literal

import pytest

from layer import field, layerclass, solidify
from layer.exceptions import CoercionError, StructureError
from layer.type_resolution import coerce

# ---------------------------------------------------------------------------
# List[T]
# ---------------------------------------------------------------------------


class TestListCoercion:
    def test_List_int_comma_separated(self):
        assert coerce("1, 2, 3", list[int]) == [1, 2, 3]

    def test_List_int_json_array_string(self):
        assert coerce('["1", "2", "3"]', list[int]) == [1, 2, 3]

    def test_List_str_keeps_items_as_strings(self):
        assert coerce("a, b, c", list[str]) == ["a", "b", "c"]

    def test_List_already_correct_type(self):
        assert coerce([1, 2], list[int]) == [1, 2]

    def test_bare_list_no_item_coercion(self):
        # bare list — no inner-type info, just parse the string
        assert coerce("a, b", list) == ["a", "b"]


# ---------------------------------------------------------------------------
# Dict[K, V]
# ---------------------------------------------------------------------------


class TestDictCoercion:
    def test_Dict_str_int_from_key_value_string(self):
        assert coerce("a=1, b=2", dict[str, int]) == {"a": 1, "b": 2}

    def test_Dict_str_int_from_json_string(self):
        assert coerce('{"a": "1", "b": "2"}', dict[str, int]) == {"a": 1, "b": 2}

    def test_Dict_already_correct_type(self):
        assert coerce({"a": 1}, dict[str, int]) == {"a": 1}

    def test_bare_dict_no_value_coercion(self):
        # bare dict — values stay as strings
        result = coerce("a=1", dict)
        assert result == {"a": "1"}


# ---------------------------------------------------------------------------
# T | None
# ---------------------------------------------------------------------------


class TestOptionalCoercion:
    def test_none_returns_none(self):
        assert coerce(None, int | None) is None

    def test_string_coerced_to_inner_type(self):
        assert coerce("42", int | None) == 42

    def test_already_correct_inner_type(self):
        assert coerce(7, int | None) == 7


# ---------------------------------------------------------------------------
# A | B
# ---------------------------------------------------------------------------


class TestUnionCoercion:
    def test_tries_first_type_first(self):
        result = coerce("123", int | str)
        assert result == 123
        assert isinstance(result, int)

    def test_order_matters_str_before_int(self):
        result = coerce("123", str | int)
        assert result == "123"
        assert isinstance(result, str)

    def test_falls_through_to_next_type_on_failure(self):
        result = coerce("abc", int | str)
        assert result == "abc"
        assert isinstance(result, str)

    def test_all_fail_raises_coercion_error(self):
        with pytest.raises(CoercionError):
            coerce("not-a-number", int | float)


# ---------------------------------------------------------------------------
# Literal
# ---------------------------------------------------------------------------


class TestLiteralCoercion:
    def test_valid_value_passes_through(self):
        assert coerce("dev", Literal["dev", "prod"]) == "dev"

    def test_invalid_value_raises_structure_error(self):
        with pytest.raises(StructureError):
            coerce("staging", Literal["dev", "prod"])

    def test_integer_literal(self):
        assert coerce(1, Literal[1, 2, 3]) == 1

    def test_invalid_integer_literal_raises(self):
        with pytest.raises(StructureError):
            coerce(5, Literal[1, 2, 3])


# ---------------------------------------------------------------------------
# Tuple[T, ...]
# ---------------------------------------------------------------------------


class TestTupleCoercion:
    def test_fixed_length_coerces_by_position(self):
        assert coerce("1, hello", tuple[int, str]) == (1, "hello")

    def test_variable_length_homogeneous(self):
        assert coerce("1, 2, 3", tuple[int, ...]) == (1, 2, 3)

    def test_already_a_list_coerces_to_tuple(self):
        assert coerce([1, 2], tuple[int, ...]) == (1, 2)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


class TestDataclassCoercion:
    def test_dict_instantiates_dataclass(self):
        @dataclasses.dataclass
        class Point:
            x: int
            y: int

        result = coerce({"x": 1, "y": 2}, Point)
        assert isinstance(result, Point)
        assert result.x == 1
        assert result.y == 2

    def test_non_dict_not_coerced(self):
        @dataclasses.dataclass
        class Point:
            x: int
            y: int

        # A non-dict value with no matching conversion is returned as-is
        p = Point(x=3, y=4)
        assert coerce(p, Point) is p


# ---------------------------------------------------------------------------
# Pydantic v2 (skipped when not installed)
# ---------------------------------------------------------------------------

pydantic = pytest.importorskip("pydantic", reason="pydantic not installed")


class TestPydanticCoercion:
    def test_dict_instantiates_pydantic_model(self):
        from pydantic import BaseModel

        class Address(BaseModel):
            street: str
            city: str

        result = coerce({"street": "123 Main St", "city": "Anytown"}, Address)
        assert isinstance(result, Address)
        assert result.city == "Anytown"


# ---------------------------------------------------------------------------
# Integration: solidify() with advanced types
# ---------------------------------------------------------------------------


class TestSolidifyIntegration:
    def test_List_int_via_solidify(self):
        @layerclass
        class C:
            scores: list[int] = field(list[int], default=None)

        c = solidify({"scores": "10, 20, 30"}, C)
        assert c.scores == [10, 20, 30]

    def test_Optional_int_via_solidify(self):
        @layerclass
        class C:
            port: int | None = field(int | None, default=None)

        assert solidify({"port": "8080"}, C).port == 8080
        assert solidify({"port": None}, C).port is None

    def test_Dict_str_int_via_solidify(self):
        @layerclass
        class C:
            scores: dict[str, int] = field(dict[str, int], default=None)

        c = solidify({"scores": "a=1, b=2"}, C)
        assert c.scores == {"a": 1, "b": 2}

    def test_Literal_valid_via_solidify(self):
        @layerclass
        class C:
            env: Literal["dev", "prod"] = field(Literal["dev", "prod"], default="dev")

        c = solidify({"env": "prod"}, C)
        assert c.env == "prod"

    def test_Literal_invalid_raises_structure_error(self):
        @layerclass
        class C:
            env: Literal["dev", "prod"] = field(Literal["dev", "prod"], default="dev")

        with pytest.raises(StructureError):
            solidify({"env": "staging"}, C)

    def test_Union_via_solidify(self):
        @layerclass
        class C:
            value: int | str = field(int | str, default=None)

        c = solidify({"value": "42"}, C)
        assert c.value == 42
        assert isinstance(c.value, int)
