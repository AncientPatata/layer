# Validation

Validation in Layer is always explicit — it never runs automatically during `load()`. This separation lets you load config quickly and run only the checks that are relevant to the current context.

## Categories

Validators are grouped by named categories. When you call `validate()`, you choose which categories to run. Bare (uncategorized) validators always run regardless of what categories you request.

```python
@layerclass
class DBConfig:
    host: str = field(str, default="localhost")

    # Bare — runs on every validate() call
    port: int = field(int, is_port, default=5432)

    # Only checked when "production_cluster" is requested
    ssl_cert: str = field(str, default=None, production_cluster=[require, path_exists])
    password: str = field(str, default=None, production_cluster=[require], secret=True)
```

```python
pipeline.validate(["production_cluster"]).raise_if_invalid()  # cluster rules + bare
pipeline.validate(["local_dev"]).raise_if_invalid()           # dev rules + bare
pipeline.validate([]).raise_if_invalid()                      # bare only
pipeline.validate("*").raise_if_invalid()                     # every category + bare
```

To validate specific fields rather than the whole schema — useful in hot-reload callbacks or after a `set()` call — pass a `fields` list:

```python
pipeline.validate(["production_cluster"], fields=["ssl_cert", "password"]).raise_if_invalid()
```

## Built-in Single-Field Validators

```python
from layer import (
    require, optional, not_empty, one_of, in_range, is_port, is_url,
    is_positive, regex, min_length, max_length, path_exists, instance_of, each_item,
)
```

| Validator | What it checks |
|---|---|
| `require` | value is not `None` |
| `not_empty` | not `None`, `""`, `[]`, or `{}` |
| `optional` | always passes — documents that `None` is intentional |
| `one_of("a", "b")` | value is one of the given choices |
| `in_range(lo, hi)` | numeric value within `[lo, hi]` |
| `is_port` | integer in `1–65535` |
| `is_url` | starts with `http://` or `https://` |
| `is_positive` | numeric `> 0` |
| `regex(pattern)` | string matches the regex |
| `min_length(n)` | string/list length `>= n` |
| `max_length(n)` | string/list length `<= n` |
| `path_exists` | path exists on the filesystem |
| `instance_of(T)` | `isinstance(value, T)` |
| `each_item(validator)` | applies any validator to every item in a list |

### `each_item` example

```python
@layerclass
class Config:
    allowed_schemes: list = field(
        list,
        each_item(one_of("http", "https", "grpc")),
        default=[]
    )
```

## Built-in Cross-Field Validators

These validators inspect other fields on the config to enforce relational constraints.

```python
from layer import requires_if, requires_any, requires_all, mutually_exclusive, depends_on
```

| Validator | When it raises |
|---|---|
| `requires_if("other", value)` | this field is `None` when `other == value` |
| `requires_any("a", "b", ...)` | all listed fields are `None` |
| `requires_all("a", "b", ...)` | some but not all listed fields are set |
| `mutually_exclusive("a", "b", ...)` | more than one listed field is set |
| `depends_on("a", "b", ...)` | this field is set but a dependency is `None` |

```python
@layerclass
class AuthConfig:
    # At least one auth method must be configured
    api_key:     str = field(str, default=None, auth=[requires_any("api_key", "client_cert")])
    # client_cert requires client_key to also be set
    client_cert: str = field(str, default=None, auth=[depends_on("client_key")])
    client_key:  str = field(str, default=None)
    # Cannot use both auth methods simultaneously
    auth_mode:   str = field(str, default=None, auth=[mutually_exclusive("api_key", "client_cert")])
```

## Custom Validators

Any callable with the signature `(value, field_name, config) -> True | raise ValidationError` is a valid validator. The `config` argument gives you access to the full config object, so custom validators can also do cross-field checks.

```python
from layer import ValidationError

def no_localhost(value, field_name, config):
    """Reject localhost in external-facing endpoints."""
    if value and "localhost" in value:
        raise ValidationError(
            field_name,
            "localhost is not allowed for external endpoints",
            "no_localhost",
            "external_api",
        )
    return True

def must_exceed(other_field):
    """Value must be strictly greater than another field's value."""
    def _check(value, field_name, config):
        other = getattr(config, other_field, None)
        if value is not None and other is not None and value <= other:
            raise ValidationError(
                field_name,
                f"Must be greater than '{other_field}' ({other})",
                "must_exceed",
                "unknown",
            )
        return True
    return _check

def consistent_tls(value, field_name, config):
    """Both cert and key must be set together, or neither."""
    has_cert = bool(getattr(config, "tls_cert", None))
    has_key  = bool(getattr(config, "tls_key", None))
    if has_cert != has_key:
        raise ValidationError(
            field_name,
            "tls_cert and tls_key must both be set or both be absent",
            "consistent_tls",
            "unknown",
        )
    return True

@layerclass
class ServerConfig:
    endpoint:           str = field(str, default=None, external=[require, is_url, no_localhost])
    connect_timeout_ms: int = field(int, default=1000)
    read_timeout_ms:    int = field(int, default=5000, common=[must_exceed("connect_timeout_ms")])
    tls_cert:           str = field(str, default=None, tls=[consistent_tls])
    tls_key:            str = field(str, default=None)
```

## Class-Level Validators

For validators that need `self` — stateful checks, filesystem access, or multi-field invariants — use `@validator` and `@root_validator`:

```python
import os
from layer import validator, root_validator, ValidationError, ConfigError

@layerclass
class TLSConfig:
    cert_path: str = field(str, default=None)
    key_path:  str = field(str, default=None)

    @validator("cert_path", "key_path", categories=["secure_node"])
    def _files_exist(self, field_name, value):
        if value and not os.path.exists(value):
            raise ValidationError(
                field_name,
                f"File not found: {value}",
                "file_check",
                "secure_node",
            )

    @root_validator(categories=["secure_node"])
    def _cert_and_key_together(self):
        if bool(self.cert_path) != bool(self.key_path):
            raise ConfigError("cert_path and key_path must both be set or both be absent")
```

`@validator` runs once per listed field and receives `(self, field_name, value)`. `@root_validator` runs after all field validators with only `self` — it's the right place for invariants that span multiple fields and can't be expressed as a single-field rule.

Both support `categories=`. Omit it to make the validator bare (runs on every `validate()` call).

## Parsers

Parsers are transform functions that normalize raw values *before* type coercion. They're distinct from validators: parsers mutate, validators assert. The separation matters because loading and validation are different concerns — sometimes you need to clean raw input before it's even in a state worth validating.

```python
from layer import parser

@layerclass
class PaymentConfig:
    amount_cents: int = field(int, default=0)
    endpoint:     str = field(str, default=None, prod=[require, is_url])

    @parser("amount_cents")
    def _clean_amount(self, value):
        """Strip currency symbols and thousands separators before int coercion."""
        if isinstance(value, str):
            return value.strip().lstrip("$€£").replace(",", "").replace(".", "")
        return value

    @parser("endpoint", "callback_url")
    def _normalize_url(self, value):
        """Remove trailing slashes so validators and interpolation work consistently."""
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return value
```

Parsers run during `solidify()`, `solidify_env()`, and `set()` — anywhere a value is written to a field. They receive the raw incoming value and must return the transformed value.

Use parsers for: stripping whitespace, removing formatting characters (thousands separators, currency symbols), normalizing casing, expanding shorthand values, or any transformation that should be transparent to the rest of the pipeline.

## Solidify Mode (Coercion Strictness)

`SolidifyMode` controls how each provider's raw data is handled when it doesn't match your schema.

| Mode | Unknown keys | Type coercion errors |
|---|---|---|
| `LAX` | silently ignored | swallowed, raw value kept |
| `STANDARD` (default) | silently ignored | raises `CoercionError` |
| `STRICT` | raises `StructureError` | no coercion attempted |

```python
from layer import ConfigPipeline, SolidifyMode

pipeline = ConfigPipeline(AppConfig, mode=SolidifyMode.STRICT)
```

`STRICT` is useful in CI or schema-validation contexts where you want to catch any drift between your config files and your schema.