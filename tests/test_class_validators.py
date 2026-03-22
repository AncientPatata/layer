"""Tests for @parser, @validator, and @root_validator class-level decorators."""

import os
import pytest
from layer import (
    layer_obj,
    field,
    parser,
    validator,
    root_validator,
    solidify,
    solidify_env,
)
from layer.exceptions import ValidationError, ConfigError


# ---------------------------------------------------------------------------
# @parser
# ---------------------------------------------------------------------------


@layer_obj
class EndpointConfig:
    endpoint: str = field(str, default=None)
    other: str = field(str, default="unchanged")

    @parser("endpoint")
    def _clean_endpoint(self, value):
        if not value:
            return value
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            return f"https://{value}"
        return value


class TestParser:
    def test_parser_runs_during_solidify(self):
        c = solidify({"endpoint": "example.com/"}, EndpointConfig)
        assert c.endpoint == "https://example.com"

    def test_parser_strips_trailing_slash(self):
        c = solidify({"endpoint": "https://example.com/"}, EndpointConfig)
        assert c.endpoint == "https://example.com"

    def test_parser_runs_during_set(self):
        c = EndpointConfig()
        c.set("endpoint", "example.com", source="test")
        assert c.endpoint == "https://example.com"

    def test_parser_does_not_run_for_other_fields(self):
        c = solidify({"other": "  value  "}, EndpointConfig)
        assert c.other == "  value  "

    def test_parser_does_not_run_during_default_init(self):
        # Default is None — parser would receive None, which it passes through
        c = EndpointConfig()
        assert c.endpoint is None

    def test_parser_runs_during_solidify_env(self, monkeypatch):
        monkeypatch.setenv("APP_ENDPOINT", "env.example.com/")
        c = solidify_env("APP", EndpointConfig)
        assert c.endpoint == "https://env.example.com"

    def test_multiple_parsers_run_in_order(self):
        @layer_obj
        class C:
            value: str = field(str, default=None)

            @parser("value")
            def _step1(self, v):
                return (v or "") + "-step1"

            @parser("value")
            def _step2(self, v):
                return (v or "") + "-step2"

        c = solidify({"value": "x"}, C)
        assert c.value == "x-step1-step2"


# ---------------------------------------------------------------------------
# @validator
# ---------------------------------------------------------------------------


@layer_obj
class TLSConfig:
    enabled: bool = field(bool, default=False)
    cert: str = field(str, default=None)
    key: str = field(str, default=None)

    @validator("cert", "key")
    def _files_exist(self, field_name, value):
        if value and not os.path.exists(value):
            raise ValidationError(
                field_name, f"File not found: {value}", "path_check", "bare"
            )

    @validator("cert", categories=["production"])
    def _cert_required_in_prod(self, field_name, value):
        if self.enabled and not value:
            raise ValidationError(
                field_name,
                "cert required when TLS is enabled",
                "cert_check",
                "production",
            )


class TestValidator:
    def test_bare_validator_runs_always(self):
        c = TLSConfig()
        c.cert = "/nonexistent/cert.pem"
        result = c.validate()
        assert not result.is_valid
        assert any("cert" in e.field for e in result.errors)

    def test_bare_validator_passes_when_value_ok(self):
        c = TLSConfig()
        # cert is None — validator skips (value falsy)
        result = c.validate()
        assert result.is_valid

    def test_category_validator_runs_when_category_requested(self):
        c = TLSConfig()
        c.enabled = True
        # cert is None — production validator should fail
        result = c.validate(["production"])
        assert not result.is_valid
        assert any("cert" in e.field for e in result.errors)

    def test_category_validator_skips_when_different_category(self):
        c = TLSConfig()
        c.enabled = True
        # "staging" is not "production" — validator should not run
        result = c.validate(["staging"])
        assert result.is_valid

    def test_validator_applied_to_multiple_fields(self):
        c = TLSConfig()
        c.cert = "/bad/cert"
        c.key = "/bad/key"
        result = c.validate()
        # Both cert and key fail — two errors expected
        assert len(result.errors) == 2

    def test_validator_passes_contributes_no_errors(self):
        c = TLSConfig()
        result = c.validate()
        assert result.is_valid

    def test_wildcard_categories_runs_category_validators(self):
        c = TLSConfig()
        c.enabled = True
        result = c.validate("*")
        assert not result.is_valid


# ---------------------------------------------------------------------------
# @root_validator
# ---------------------------------------------------------------------------


@layer_obj
class DBConfig:
    driver: str = field(str, default="postgres")
    dsn: str = field(str, default=None)
    host: str = field(str, default=None)

    @root_validator(categories=["database"])
    def _check_connection_strategy(self):
        if self.dsn and self.host:
            raise ConfigError("Cannot specify both 'dsn' and 'host'.")
        if not self.dsn and not self.host:
            raise ConfigError("Must specify either 'dsn' or 'host'.")

    @root_validator()
    def _driver_always_required(self):
        if not self.driver:
            raise ConfigError("driver must be set")


class TestRootValidator:
    def test_bare_root_validator_always_runs(self):
        c = DBConfig()
        c.driver = ""
        c.dsn = "postgres://..."
        result = c.validate()
        assert not result.is_valid
        root_errs = [e for e in result.errors if e.field == "__root__"]
        assert len(root_errs) >= 1

    def test_category_root_validator_runs_when_requested(self):
        c = DBConfig()
        # Both dsn and host set — should fail
        c.dsn = "postgres://..."
        c.host = "localhost"
        result = c.validate(["database"])
        assert not result.is_valid
        assert any(e.field == "__root__" for e in result.errors)

    def test_category_root_validator_skips_when_not_requested(self):
        c = DBConfig()
        c.dsn = "postgres://..."
        c.host = "localhost"
        # Only "other" category — database root_validator should not run
        result = c.validate(["other"])
        assert result.is_valid

    def test_root_validator_passes_contributes_no_errors(self):
        c = DBConfig()
        c.dsn = "postgres://localhost/mydb"
        result = c.validate(["database"])
        assert result.is_valid

    def test_root_validator_error_has_root_field(self):
        c = DBConfig()
        c.dsn = "postgres://..."
        c.host = "localhost"
        result = c.validate(["database"])
        err = next(e for e in result.errors if e.field == "__root__")
        assert "dsn" in err.message or "host" in err.message

    def test_root_validator_runs_after_field_validators(self):
        # Ensure field errors and root errors are both collected
        from layer import require

        @layer_obj
        class C:
            value: str = field(str, require, default=None)

            @root_validator()
            def _always_fails(self):
                raise ConfigError("root always fails")

        c = C()
        result = c.validate()
        field_errs = [e for e in result.errors if e.field != "__root__"]
        root_errs = [e for e in result.errors if e.field == "__root__"]
        assert len(field_errs) >= 1
        assert len(root_errs) >= 1
