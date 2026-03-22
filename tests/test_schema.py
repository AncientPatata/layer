"""Tests for JSON Schema generation."""

import json

import pytest
from conftest import TlsConfig

from layer import field, in_range, layerclass, one_of, require


@layerclass
class SchemaConfig:
    endpoint: str = field(str, cluster=[require], description="Cluster URL")
    port: int = field(int, in_range(1, 65535), default=5000, description="Port number")
    output: str = field(
        str,
        common=[one_of("json", "yaml", "table")],
        default="json",
        description="Format",
    )
    debug: bool = field(bool, default=False, description="Debug mode")
    tls: TlsConfig = field(TlsConfig, description="TLS settings", default=None)


@pytest.fixture(scope="module")
def schema():
    return SchemaConfig.json_schema()


def test_draft07_header(schema):
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["type"] == "object"


def test_properties_present(schema):
    assert "endpoint" in schema["properties"]
    assert "port" in schema["properties"]


def test_type_mapping(schema):
    props = schema["properties"]
    assert props["endpoint"]["type"] == "string"
    assert props["port"]["type"] == "integer"
    assert props["debug"]["type"] == "boolean"


def test_descriptions(schema):
    props = schema["properties"]
    assert props["endpoint"]["description"] == "Cluster URL"
    assert props["port"]["description"] == "Port number"


def test_defaults(schema):
    props = schema["properties"]
    assert props["port"]["default"] == 5000
    assert props["output"]["default"] == "json"


def test_enum_from_one_of(schema):
    assert schema["properties"]["output"]["enum"] == ["json", "yaml", "table"]


def test_range_from_in_range(schema):
    port = schema["properties"]["port"]
    assert port["minimum"] == 1
    assert port["maximum"] == 65535


def test_required_fields(schema):
    assert "endpoint" in schema.get("required", [])


def test_nested_object(schema):
    tls = schema["properties"]["tls"]
    assert tls["type"] == "object"
    assert "ca" in tls["properties"]


def test_json_serializable(schema):
    output = json.dumps(schema, indent=2)
    assert "endpoint" in output
