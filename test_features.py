"""
Test script for Layer.py new features.
Run: python test_features.py
"""

import sys
import os
import json
import tempfile

# Add the layer package to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from layer.core import layer_obj, field, _is_layer_obj
from layer.solidify import solidify, solidify_env, solidify_file, write_file
from layer.layering import LayerRule
from layer.validation import (
    require,
    one_of,
    in_range,
    path_exists,
    optional,
    requires_if,
    requires_any,
    mutually_exclusive,
    depends_on,
    regex,
    min_length,
    max_length,
    not_empty,
    is_url,
    is_positive,
    is_port,
    each_item,
)
from layer.exceptions import ConfigError, ValidationError, InterpolationError

passed = 0
failed = 0


def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  ✓ {name}")
        passed += 1
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        failed += 1


# ═══════════════════════════════════════════════
print("\n1. Meta on FieldDef")
# ═══════════════════════════════════════════════


@layer_obj
class MetaConfig:
    endpoint: str = field(
        str,
        cluster=[require],
        meta={
            "cli_option": "--endpoint",
            "envvar": "AK__Endpoint",
        },
        description="ArmoniK cluster endpoint URL",
    )


def test_meta_stored():
    fdef = MetaConfig._field_defs["endpoint"]
    assert fdef.meta["cli_option"] == "--endpoint"
    assert fdef.meta["envvar"] == "AK__Endpoint"


test("meta dict stored on field def", test_meta_stored)


def test_description_stored():
    fdef = MetaConfig._field_defs["endpoint"]
    assert fdef.description == "ArmoniK cluster endpoint URL"


test("description stored on field def", test_description_stored)


def test_meta_accessible_class_level():
    assert "endpoint" in MetaConfig._field_defs
    assert MetaConfig._field_defs["endpoint"].meta["cli_option"] == "--endpoint"


test(
    "meta accessible at class level (no instance needed)",
    test_meta_accessible_class_level,
)


# ═══════════════════════════════════════════════
print("\n2. _field_defs as class attribute")
# ═══════════════════════════════════════════════


@layer_obj
class ClassAttrConfig:
    port: int = field(int, default=5000)


def test_field_defs_class_level():
    assert hasattr(ClassAttrConfig, "_field_defs")
    assert "port" in ClassAttrConfig._field_defs


test(
    "_field_defs accessible on class without instantiation", test_field_defs_class_level
)


def test_field_defs_instance_level():
    c = ClassAttrConfig()
    assert "port" in c._field_defs


test("_field_defs also accessible on instance", test_field_defs_instance_level)


# ═══════════════════════════════════════════════
print("\n3. Type coercion in solidify()")
# ═══════════════════════════════════════════════


@layer_obj
class CoerceConfig:
    port: int = field(int, default=5000)
    debug: bool = field(bool, default=False)
    rate: float = field(float, default=1.0)
    name: str = field(str, default="test")
    tags: list = field(list, default=None)
    labels: dict = field(dict, default=None)


def test_coerce_str_to_int():
    c = solidify({"port": "8080"}, CoerceConfig)
    assert c.port == 8080
    assert isinstance(c.port, int)


test("solidify coerces '8080' -> int 8080", test_coerce_str_to_int)


def test_coerce_str_to_bool():
    c = solidify({"debug": "true"}, CoerceConfig)
    assert c.debug is True


test("solidify coerces 'true' -> bool True", test_coerce_str_to_bool)


def test_coerce_str_to_float():
    c = solidify({"rate": "3.14"}, CoerceConfig)
    assert abs(c.rate - 3.14) < 0.001


test("solidify coerces '3.14' -> float 3.14", test_coerce_str_to_float)


def test_coerce_str_to_list():
    c = solidify({"tags": "web, prod"}, CoerceConfig)
    assert c.tags == ["web", "prod"]


test("solidify coerces 'web, prod' -> list ['web', 'prod']", test_coerce_str_to_list)


def test_coerce_str_to_dict():
    c = solidify({"labels": "env=prod, tier=web"}, CoerceConfig)
    assert c.labels == {"env": "prod", "tier": "web"}


test(
    "solidify coerces 'env=prod, tier=web' -> dict {'env': 'prod', 'tier': 'web'}",
    test_coerce_str_to_dict,
)


def test_coerce_already_correct_type():
    c = solidify({"port": 9090}, CoerceConfig)
    assert c.port == 9090


test("solidify leaves already-correct types alone", test_coerce_already_correct_type)


def test_coerce_disabled():
    c = solidify({"port": "8080"}, CoerceConfig, coerce=False)
    assert c.port == "8080"  # stays string


test("solidify coerce=False skips coercion", test_coerce_disabled)


# ═══════════════════════════════════════════════
print("\n4. Field descriptions")
# ═══════════════════════════════════════════════


@layer_obj
class DescConfig:
    endpoint: str = field(str, description="The cluster endpoint URL")
    port: int = field(int, default=5000, description="Port number")
    debug: bool = field(bool, default=False)  # no description


def test_description_in_explain():
    c = DescConfig()
    info = c.explain()
    ep = [i for i in info if i["field"] == "endpoint"][0]
    assert ep["description"] == "The cluster endpoint URL"
    db = [i for i in info if i["field"] == "debug"][0]
    assert db["description"] is None


test("descriptions appear in explain() output", test_description_in_explain)


# ═══════════════════════════════════════════════
print("\n5. Structured explain()")
# ═══════════════════════════════════════════════


@layer_obj
class ExplainConfig:
    endpoint: str = field(str, cluster=[require], description="Cluster URL")
    output: str = field(
        str, common=[one_of("json", "yaml")], default="json", description="Format"
    )


def test_explain_structure():
    c = ExplainConfig()
    c.set("endpoint", "http://localhost", source="cli")
    info = c.explain()
    assert isinstance(info, list)
    assert len(info) == 2
    ep = info[0]
    assert ep["field"] == "endpoint"
    assert ep["value"] == "http://localhost"
    assert ep["source"] == "cli"
    assert ep["type"] == "str"
    assert ep["description"] == "Cluster URL"
    assert "cluster" in ep["categories"]


test("explain() returns structured list of dicts", test_explain_structure)


# ═══════════════════════════════════════════════
print("\n6. Serialization (solidify_file / write_file)")
# ═══════════════════════════════════════════════


@layer_obj
class FileConfig:
    host: str = field(str, default="localhost")
    port: int = field(int, default=5000)


def test_yaml_roundtrip():
    c = FileConfig()
    c.host = "prod.example.com"
    c.port = 9090
    with tempfile.NamedTemporaryFile(suffix=".yml", mode="w", delete=False) as f:
        path = f.name
    try:
        write_file(c, path)
        loaded = solidify_file(path, FileConfig, source="test-file")
        assert loaded.host == "prod.example.com"
        assert loaded.port == 9090
    finally:
        os.unlink(path)


test("YAML write + read roundtrip", test_yaml_roundtrip)


def test_json_roundtrip():
    c = FileConfig()
    c.host = "staging.example.com"
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        path = f.name
    try:
        write_file(c, path)
        loaded = solidify_file(path, FileConfig, source="json-file")
        assert loaded.host == "staging.example.com"
    finally:
        os.unlink(path)


test("JSON write + read roundtrip", test_json_roundtrip)


# ═══════════════════════════════════════════════
print("\n7. Nested configs")
# ═══════════════════════════════════════════════


@layer_obj
class TlsConfig:
    ca: str = field(str, description="CA certificate path", default=None)
    cert: str = field(str, description="Client certificate path", default=None)
    key: str = field(str, description="Client key path", default=None)


@layer_obj
class AppConfig:
    endpoint: str = field(str, cluster=[require], description="Cluster endpoint")
    tls: TlsConfig = field(TlsConfig, description="TLS configuration", default=None)
    output: str = field(str, common=[one_of("json", "yaml", "table")], default="json")


def test_nested_default_init():
    c = AppConfig()
    assert _is_layer_obj(c.tls)
    assert c.tls.ca is None
    assert c.tls.cert is None


test("nested config initializes with defaults", test_nested_default_init)


def test_nested_solidify_from_dict():
    data = {
        "endpoint": "http://localhost:5001",
        "tls": {
            "ca": "/etc/ssl/ca.pem",
            "cert": "/etc/ssl/cert.pem",
        },
        "output": "yaml",
    }
    c = solidify(data, AppConfig, source="config.yml")
    assert c.endpoint == "http://localhost:5001"
    assert c.tls.ca == "/etc/ssl/ca.pem"
    assert c.tls.cert == "/etc/ssl/cert.pem"
    assert c.tls.key is None
    assert c.output == "yaml"


test("nested config solidifies from dict", test_nested_solidify_from_dict)


def test_nested_to_dict():
    c = AppConfig()
    c.endpoint = "http://test"
    c.tls.ca = "/path/ca"
    d = c.to_dict()
    assert d["endpoint"] == "http://test"
    assert isinstance(d["tls"], dict)
    assert d["tls"]["ca"] == "/path/ca"


test("to_dict() recursively converts nested configs", test_nested_to_dict)


def test_nested_layer():
    base = AppConfig()
    base.endpoint = "http://base"
    base.tls.ca = "/base/ca"

    overlay_data = {"tls": {"cert": "/overlay/cert"}}
    overlay = solidify(overlay_data, AppConfig, source="overlay")

    base.layer(overlay)
    assert base.tls.ca == "/base/ca"  # preserved (not in overlay)
    assert base.tls.cert == "/overlay/cert"  # layered


test("nested layer merges recursively", test_nested_layer)


def test_nested_validate():
    c = AppConfig()
    # endpoint is required in cluster category
    result = c.validate(["cluster"])
    assert not result.is_valid
    # Find the endpoint error
    ep_errors = [e for e in result.errors if "endpoint" in e.field]
    assert len(ep_errors) > 0


test("nested validation works", test_nested_validate)


def test_nested_yaml_roundtrip():
    c = AppConfig()
    c.endpoint = "http://test"
    c.tls.ca = "/ca"
    c.tls.cert = "/cert"
    with tempfile.NamedTemporaryFile(suffix=".yml", mode="w", delete=False) as f:
        path = f.name
    try:
        write_file(c, path)
        loaded = solidify_file(path, AppConfig, source="file")
        assert loaded.endpoint == "http://test"
        assert loaded.tls.ca == "/ca"
        assert loaded.tls.cert == "/cert"
    finally:
        os.unlink(path)


test("nested config YAML roundtrip", test_nested_yaml_roundtrip)


def test_nested_copy():
    c = AppConfig()
    c.tls.ca = "/original"
    c2 = c.copy()
    c2.tls.ca = "/changed"
    assert c.tls.ca == "/original"  # original unaffected


test("copy() deep copies nested configs", test_nested_copy)


# ═══════════════════════════════════════════════
print("\n8. JSON Schema generation")
# ═══════════════════════════════════════════════


@layer_obj
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


def test_json_schema_basic():
    schema = SchemaConfig.json_schema()
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "endpoint" in schema["properties"]
    assert "port" in schema["properties"]


test("json_schema() produces valid structure", test_json_schema_basic)


def test_json_schema_types():
    schema = SchemaConfig.json_schema()
    assert schema["properties"]["endpoint"]["type"] == "string"
    assert schema["properties"]["port"]["type"] == "integer"
    assert schema["properties"]["debug"]["type"] == "boolean"


test("json_schema() maps Python types to JSON types", test_json_schema_types)


def test_json_schema_descriptions():
    schema = SchemaConfig.json_schema()
    assert schema["properties"]["endpoint"]["description"] == "Cluster URL"
    assert schema["properties"]["port"]["description"] == "Port number"


test("json_schema() includes descriptions", test_json_schema_descriptions)


def test_json_schema_defaults():
    schema = SchemaConfig.json_schema()
    assert schema["properties"]["port"]["default"] == 5000
    assert schema["properties"]["output"]["default"] == "json"


test("json_schema() includes defaults", test_json_schema_defaults)


def test_json_schema_enum():
    schema = SchemaConfig.json_schema()
    assert schema["properties"]["output"]["enum"] == ["json", "yaml", "table"]


test("json_schema() extracts enum from one_of", test_json_schema_enum)


def test_json_schema_range():
    schema = SchemaConfig.json_schema()
    assert schema["properties"]["port"]["minimum"] == 1
    assert schema["properties"]["port"]["maximum"] == 65535


test("json_schema() extracts min/max from in_range", test_json_schema_range)


def test_json_schema_required():
    schema = SchemaConfig.json_schema()
    assert "endpoint" in schema.get("required", [])


test("json_schema() marks required fields", test_json_schema_required)


def test_json_schema_nested():
    schema = SchemaConfig.json_schema()
    tls_prop = schema["properties"]["tls"]
    assert tls_prop["type"] == "object"
    assert "ca" in tls_prop["properties"]


test("json_schema() handles nested @layer_obj recursively", test_json_schema_nested)


def test_json_schema_serializable():
    schema = SchemaConfig.json_schema()
    output = json.dumps(schema, indent=2)
    assert "endpoint" in output


test("json_schema() output is JSON-serializable", test_json_schema_serializable)


# ═══════════════════════════════════════════════
print("\n9. Config diffing")
# ═══════════════════════════════════════════════


def test_diff_detects_changes():
    a = AppConfig()
    a.endpoint = "http://a"
    a.output = "json"

    b = AppConfig()
    b.endpoint = "http://b"
    b.output = "json"

    diffs = a.diff(b)
    assert len(diffs) == 1
    assert diffs[0]["field"] == "endpoint"
    assert diffs[0]["old_value"] == "http://a"
    assert diffs[0]["new_value"] == "http://b"


test("diff() detects changed fields", test_diff_detects_changes)


def test_diff_no_changes():
    a = AppConfig()
    b = AppConfig()
    diffs = a.diff(b)
    assert len(diffs) == 0


test("diff() returns empty list when identical", test_diff_no_changes)


def test_diff_nested():
    a = AppConfig()
    a.tls.ca = "/old/ca"
    b = AppConfig()
    b.tls.ca = "/new/ca"
    diffs = a.diff(b)
    ca_diff = [d for d in diffs if d["field"] == "tls.ca"]
    assert len(ca_diff) == 1


test("diff() works recursively on nested configs", test_diff_nested)


# ═══════════════════════════════════════════════
print("\n10. Frozen config")
# ═══════════════════════════════════════════════


def test_freeze_prevents_mutation():
    c = AppConfig()
    c.endpoint = "http://test"
    c.freeze()
    try:
        c.endpoint = "http://changed"
        assert False, "Should have raised"
    except AttributeError:
        pass


test("freeze() prevents field mutation", test_freeze_prevents_mutation)


def test_frozen_property():
    c = AppConfig()
    assert not c.frozen
    c.freeze()
    assert c.frozen


test("frozen property reflects state", test_frozen_property)


def test_freeze_nested():
    c = AppConfig()
    c.tls.ca = "/ca"
    c.freeze()
    try:
        c.tls.ca = "/changed"
        assert False, "Should have raised on nested"
    except AttributeError:
        pass


test("freeze() recursively freezes nested configs", test_freeze_nested)

# ═══════════════════════════════════════════════
print("\n11. Interpolation")
# ═══════════════════════════════════════════════


@layer_obj
class InterpolationConfig:
    host: str = field(str, default="localhost")
    port: int = field(int, default=8080)
    url: str = field(str, default="http://${host}:${port}/api")
    nested_url: str = field(str, default="${url}/v1")


def test_interpolation_resolves():
    c = InterpolationConfig()
    c.resolve()
    assert c.url == "http://localhost:8080/api"
    assert c.nested_url == "http://localhost:8080/api/v1"


test("resolve() substitutes variables correctly", test_interpolation_resolves)

# ═══════════════════════════════════════════════
print("\n12. Source History")
# ═══════════════════════════════════════════════


def test_source_history():
    c = FileConfig()
    c.set("host", "first.com", source="init")
    c.set("host", "second.com", source="update")

    assert c.source_of("host") == "update"
    history = c.source_history_of("host")
    assert len(history) >= 2
    assert history[-1].source == "update"
    assert history[-1].value == "second.com"


test("set() pushes updates to source history correctly", test_source_history)

# ═══════════════════════════════════════════════
print("\n13. Secret Redaction")
# ═══════════════════════════════════════════════


@layer_obj
class SecretConfig:
    user: str = field(str, default="admin")
    password: str = field(str, secret=True, default="supersecret")


def test_secret_redaction_to_dict():
    c = SecretConfig()
    d_redacted = c.to_dict(redact=True)
    d_plain = c.to_dict(redact=False)

    assert d_redacted["password"] == "***"
    assert d_redacted["user"] == "admin"
    assert d_plain["password"] == "supersecret"


test("to_dict() handles secret redaction", test_secret_redaction_to_dict)


def test_secret_redaction_explain():
    c = SecretConfig()
    info = c.explain(redact=True)
    pw_info = [i for i in info if i["field"] == "password"][0]
    assert pw_info["value"] == "***"


test("explain() handles secret redaction", test_secret_redaction_explain)

# ═══════════════════════════════════════════════
print("\n14. Cross-Field Validation")
# ═══════════════════════════════════════════════


@layer_obj
class CrossValidConfig:
    auth_type: str = field(str, default="none")
    token: str = field(str, default=None, auth=[requires_if("auth_type", "bearer")])


def test_requires_if_validator():
    c = CrossValidConfig()
    c.auth_type = "bearer"
    # Token is missing, should fail
    res = c.validate(["auth"])
    assert not res.is_valid

    # Provide token, should pass
    c.token = "abc-123"
    assert c.validate(["auth"]).is_valid


test(
    "requires_if validator enforces conditional dependencies",
    test_requires_if_validator,
)

# ═══════════════════════════════════════════════
print("\n15. Layering Rules")
# ═══════════════════════════════════════════════


@layer_obj
class MergeConfig:
    items: list = field(list, default=["a"])
    flags: dict = field(dict, default={"debug": True})


def test_layer_append():
    base = MergeConfig()
    base.set("items", ["a"], source="base")

    overlay = MergeConfig()
    overlay.set("items", ["b", "c"], source="overlay")

    base.layer(overlay, rules={"items": LayerRule.APPEND})
    assert base.items == ["a", "b", "c"]


test("layer() handles LayerRule.APPEND correctly", test_layer_append)


def test_layer_merge():
    base = MergeConfig()
    base.set("flags", {"debug": True, "verbose": False}, source="base")

    overlay = MergeConfig()
    overlay.set("flags", {"verbose": True}, source="overlay")

    base.layer(overlay, rules={"flags": LayerRule.MERGE})
    assert base.flags == {"debug": True, "verbose": True}


test("layer() handles LayerRule.MERGE correctly", test_layer_merge)


# ═══════════════════════════════════════════════
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
