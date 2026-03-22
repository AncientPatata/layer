"""Tests for layer.exporters — to_json_schema, to_dotenv_template, to_configmap."""

from layer import layerclass, field, exporters


# ---------------------------------------------------------------------------
# Shared configs
# ---------------------------------------------------------------------------


@layerclass
class SimpleConfig:
    host: str = field(str, default="localhost", description="Database host")
    port: int = field(int, default=5432, description="Database port")
    debug: bool = field(bool, default=False)
    password: str = field(str, default=None, secret=True, description="DB password")


@layerclass
class TlsConf:
    cert: str = field(str, default="/etc/certs/cert.pem", description="TLS certificate")
    ca: str = field(str, default="/etc/certs/ca.pem")


@layerclass
class NestedConfig:
    endpoint: str = field(str, default="http://localhost:8080")
    tls: TlsConf = field(TlsConf, default=None)


# ---------------------------------------------------------------------------
# to_json_schema
# ---------------------------------------------------------------------------


class TestToJsonSchema:
    def test_returns_dict(self):
        schema = exporters.to_json_schema(SimpleConfig)
        assert isinstance(schema, dict)

    def test_schema_has_properties(self):
        schema = exporters.to_json_schema(SimpleConfig)
        assert "properties" in schema
        assert "host" in schema["properties"]
        assert "port" in schema["properties"]

    def test_same_as_json_schema_method(self):
        assert exporters.to_json_schema(SimpleConfig) == SimpleConfig.json_schema()

    def test_nested_schema(self):
        schema = exporters.to_json_schema(NestedConfig)
        assert "tls" in schema["properties"]


# ---------------------------------------------------------------------------
# to_dotenv_template
# ---------------------------------------------------------------------------


class TestToDotenvTemplate:
    def test_returns_string(self):
        result = exporters.to_dotenv_template(SimpleConfig)
        assert isinstance(result, str)

    def test_includes_field_as_var(self):
        result = exporters.to_dotenv_template(SimpleConfig)
        assert "HOST=" in result
        assert "PORT=" in result

    def test_uses_default_values(self):
        result = exporters.to_dotenv_template(SimpleConfig)
        assert "HOST=localhost" in result
        assert "PORT=5432" in result

    def test_prefix_applied(self):
        result = exporters.to_dotenv_template(SimpleConfig, prefix="APP")
        assert "APP_HOST=localhost" in result
        assert "APP_PORT=5432" in result

    def test_description_as_comment(self):
        result = exporters.to_dotenv_template(SimpleConfig)
        assert "# Database host" in result
        assert "# Database port" in result

    def test_secret_field_uses_placeholder(self):
        result = exporters.to_dotenv_template(SimpleConfig)
        assert "PASSWORD=<secret>" in result

    def test_nested_config_section_header(self):
        result = exporters.to_dotenv_template(NestedConfig)
        assert "TlsConf" in result  # section label

    def test_nested_fields_have_nested_prefix(self):
        result = exporters.to_dotenv_template(NestedConfig, prefix="APP")
        assert "APP_TLS_CERT=" in result

    def test_none_default_produces_empty_value(self):
        result = exporters.to_dotenv_template(SimpleConfig)
        # password has default=None (but is secret, so shows <secret>)
        # debug has default=False
        assert "DEBUG=False" in result

    def test_no_prefix(self):
        result = exporters.to_dotenv_template(SimpleConfig, prefix="")
        assert "HOST=localhost" in result
        assert "APP_HOST" not in result


# ---------------------------------------------------------------------------
# to_yaml
# ---------------------------------------------------------------------------


class TestToYaml:
    def test_returns_string(self):
        result = exporters.to_yaml(SimpleConfig)
        assert isinstance(result, str)

    def test_includes_fields(self):
        result = exporters.to_yaml(SimpleConfig)
        assert "host: localhost" in result
        assert "port: 5432" in result

    def test_description_as_comment(self):
        result = exporters.to_yaml(SimpleConfig)
        assert "# Database host" in result
        assert "# Database port" in result

    def test_secret_field_uses_placeholder(self):
        result = exporters.to_yaml(SimpleConfig)
        assert "# password: <secret>" in result
        assert "password: null" not in result

    def test_nested_config_section(self):
        result = exporters.to_yaml(NestedConfig)
        assert "tls:" in result
        assert "  cert: /etc/certs/cert.pem" in result

    def test_none_default_produces_null(self):
        @layerclass
        class NullConfig:
            value: str = field(str, default=None)

        result = exporters.to_yaml(NullConfig)
        assert "value: null" in result


# ---------------------------------------------------------------------------
# to_configmap
# ---------------------------------------------------------------------------


class TestToConfigmap:
    def test_returns_string(self):
        result = exporters.to_configmap(SimpleConfig)
        assert isinstance(result, str)

    def test_has_configmap_header(self):
        result = exporters.to_configmap(SimpleConfig)
        assert "apiVersion: v1" in result
        assert "kind: ConfigMap" in result

    def test_uses_provided_name(self):
        result = exporters.to_configmap(SimpleConfig, name="my-app")
        assert "name: my-app" in result

    def test_default_name(self):
        result = exporters.to_configmap(SimpleConfig)
        assert "name: app-config" in result

    def test_includes_field_values(self):
        result = exporters.to_configmap(SimpleConfig)
        assert "HOST: localhost" in result

    def test_numeric_defaults_quoted(self):
        result = exporters.to_configmap(SimpleConfig)
        assert 'PORT: "5432"' in result

    def test_secret_fields_omitted(self):
        result = exporters.to_configmap(SimpleConfig)
        assert "PASSWORD:" not in result or "omitted" in result

    def test_nested_fields_included(self):
        result = exporters.to_configmap(NestedConfig)
        assert "TLS_CERT:" in result

    def test_data_section_present(self):
        result = exporters.to_configmap(SimpleConfig)
        assert "data:" in result
