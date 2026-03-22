# Layer

**Deterministic, multi-source configuration with validation, provenance tracking, and hot-reloading.**

Layer is a Python library for applications that pull config from multiple places (files, environment variables, AWS SSM, HashiCorp Vault) and need to merge them reliably, validate them explicitly, and understand exactly where every value came from.

---

## Why Layer

Most config libraries give you a dict. Layer gives you a typed, validated, observable object with a clear story: every field knows which provider set it, when, and what the value was before.

The design follows a strict order of operations:

```
1. Define   →  declare your schema with @layerclass
2. Load     →  ingest providers, merge overlays, resolve ${vars}
3. Validate →  run category-specific rules
4. Freeze   →  lock the object
```

`load()` never validates. `validate()` never loads. This separation lets you load a minimal config quickly at startup and defer expensive or tricky cross-field validations to later, validate when it's needed, or run different rule sets in different environments without touching the schema.

---

## Quick Start

```python
from layer import layerclass, field, computed_field, ConfigPipeline, require, is_port
from layer.providers import FileProvider, EnvProvider

@layerclass
class AppConfig:
    host: str = field(str, default="localhost")
    port: int = field(int, default=8080, prod=[require, is_port])
    timeout_ms: int = field(int, default=5000)
    max_retries: int = field(int, default=3)

    @computed_field
    def retry_budget_ms(self) -> int:
        """Total time budget across all retry attempts."""
        return self.timeout_ms * self.max_retries


pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("config.yml"))
    .add_provider(EnvProvider("APP"))           # env vars win over file
)

config = pipeline.load()                        # ingest → merge → resolve → freeze
pipeline.validate(["prod"]).raise_if_invalid()  # validate explicitly, never inside load()

print(config.retry_budget_ms)   # 15000
print(config.host)              # whatever APP_HOST resolved to
```

---

## Installation

```bash
pip install layer

# Optional providers
pip install layer[watch]   # FileProvider(watch=True) hot-reload via watchdog
pip install layer[dotenv]  # DotEnvProvider via python-dotenv
pip install layer[aws]     # SSMProvider via boto3
pip install layer[vault]   # VaultProvider via hvac
```

---

## Nested Configs and Cross-Field Interpolation

You can nest `@layerclass` instances as typed fields. Providers merge into each sub-config independently, and `${...}` interpolation can reach across the full config tree using dot-paths.

```python
@layerclass
class DatabaseConfig:
    host: str = field(str, default="localhost")
    port: int = field(int, default=5432)
    name: str = field(str, default="myapp")

@layerclass
class AppConfig:
    database: DatabaseConfig = field(DatabaseConfig, default=None)

    # Interpolates across nested config : ${database.host} resolves at load time
    dsn: str = field(str, default="postgresql://${database.host}:${database.port}/${database.name}")
```

```yaml
# config.yml
database:
  host: db.prod.example.com
  port: 5432
  name: myapp_prod
```

```python
config = ConfigPipeline(AppConfig).add_provider(FileProvider("config.yml")).load()
print(config.dsn)  # postgresql://db.prod.example.com:5432/myapp_prod
```

Dot-notation works everywhere: `config.get("database.host")`, `on_change("database.host", callback)`, `LayerRule` overrides in `add_provider()`.

---

## Provenance Tracking

Every field records where its value came from. This makes debugging config issues in systems with many providers straightforward.

```python
config.source_of("host")
# "env:APP_HOST"

config.source_history_of("host")
# [
#   SourceEntry(source="default",     value="localhost"),
#   SourceEntry(source="config.yml",  value="db.internal"),
#   SourceEntry(source="env:APP_HOST",value="db.prod.example.com"),
# ]

config.explain()
# [
#   {"field": "host",  "value": "db.prod.example.com", "source": "env:APP_HOST",  ...},
#   {"field": "port",  "value": 5432,                  "source": "config.yml",    ...},
#   {"field": "dsn",   "value": "***",                 "source": "computed",      ...},
#   ...
# ]
```

`explain()` redacts secrets by default. Pass `full_history=True` to see the full value chain for every field.

---

## Diffing Configs

`diff()` compares two config instances and returns a structured list of what changed, including which provider each value came from. Nested fields are reported with dot-paths.

```python
before = pipeline.load()
# ... time passes, file changes ...
after  = pipeline._build_shadow()

for change in before.diff(after):
    print(change)
# {"field": "database.host", "old_value": "db-1", "new_value": "db-2",
#  "old_source": "config.yml", "new_source": "config.yml"}
```

This is what drives hot-reload callbacks internally and the same diff mechanism is available to you directly.

---

## Validation

### Categories

Attach validators to named categories. Only the categories you request are checked:

```python
@layerclass
class DBConfig:
    host: str = field(str, default="localhost")
    port: int = field(int, is_port, default=5432)  # bare validators always runs

    ssl_cert: str = field(
        str,
        default=None,
        prod=[require, path_exists],  # only checked when "prod" is requested
        dev=[optional],
    )
    password: str = field(
        str,
        default=None,
        prod=[require],
        dev=[optional],
        secret=True,
    )
```

```python
pipeline.validate(["prod"]).raise_if_invalid()   # prod rules + bare
pipeline.validate(["dev"]).raise_if_invalid()    # dev rules + bare
pipeline.validate([]).raise_if_invalid()         # bare rules only
pipeline.validate(["*"]).raise_if_invalid()      # everything
```

### Built-in Validators

```python
from layer import (
    require, optional, not_empty, one_of, in_range, is_port, is_url,
    is_positive, regex, min_length, max_length, path_exists, instance_of,
    each_item, requires_if, requires_any, requires_all,
    mutually_exclusive, depends_on,
)
```

| Validator | What it checks |
|---|---|
| `require` | value is not `None` |
| `not_empty` | not `None`, `""`, `[]`, or `{}` |
| `optional` | always passes (documentation marker) |
| `one_of("a", "b")` | value is in the given set |
| `in_range(lo, hi)` | numeric value within `[lo, hi]` |
| `is_port` | integer in `1–65535` |
| `is_url` | starts with `http://` or `https://` |
| `is_positive` | numeric value `> 0` |
| `regex(pattern)` | string matches the regex |
| `min_length(n)` / `max_length(n)` | string/list length |
| `path_exists` | path exists on the filesystem |
| `each_item(validator)` | applies any validator to every item in a list |

### Cross-Field Validators

```python
@layerclass
class AuthConfig:
    api_key: str    = field(str, default=None, auth=[requires_any("api_key", "client_cert")])
    client_cert: str = field(str, default=None, auth=[depends_on("client_key")])
    client_key: str  = field(str, default=None)
    auth_mode: str   = field(str, default=None, auth=[mutually_exclusive("api_key", "client_cert")])
```

| Validator | When it raises |
|---|---|
| `requires_if("other", value)` | this field is `None` when `other == value` |
| `requires_any("a", "b", ...)` | all listed fields are `None` |
| `requires_all("a", "b", ...)` | some but not all listed fields are set |
| `mutually_exclusive("a", "b", ...)` | more than one listed field is set |
| `depends_on("a", "b", ...)` | this field is set but a dependency is `None` |

### Custom Validators

Any callable `(value, field_name, config) -> True | raise ValidationError`:

```python
from layer import ValidationError

def no_localhost(value, field_name, config):
    if value and "localhost" in value:
        raise ValidationError(field_name, "localhost not allowed in production", "no_localhost", "prod")
    return True

@layerclass
class ServerConfig:
    endpoint: str = field(str, default=None, prod=[require, is_url, no_localhost])
```

### Class-Level Validators

For checks that need `self` or span multiple fields:

```python
from layer import validator, root_validator, ValidationError, ConfigError

@layerclass
class TLSConfig:
    cert_path: str = field(str, default=None)
    key_path: str  = field(str, default=None)

    @validator("cert_path", "key_path", categories=["prod"])
    def _files_exist(self, field_name, value):
        if value and not os.path.exists(value):
            raise ValidationError(field_name, f"File not found: {value}", "file_check", "prod")

    @root_validator(categories=["prod"])
    def _cert_and_key_together(self):
        if bool(self.cert_path) != bool(self.key_path):
            raise ConfigError("cert_path and key_path must be set together")
```

---

## Computed Fields

`@computed_field` exposes a method as a read-only property. It's evaluated on every access, appears in `to_dict()` and `explain()`, and cannot be assigned to.

```python
@layerclass
class WorkerConfig:
    timeout_ms: int  = field(int, default=5000)
    max_retries: int = field(int, default=3)
    tls_cert: str    = field(str, default=None)
    tls_key: str     = field(str, default=None)
    worker_ids: list = field(list, default=None)

    @computed_field
    def retry_budget_ms(self) -> int:
        """Total time budget across all retry attempts."""
        return self.timeout_ms * self.max_retries

    @computed_field
    def tls_enabled(self) -> bool:
        """TLS is active only when both cert and key are configured."""
        return bool(self.tls_cert and self.tls_key)

    @computed_field
    def worker_count(self) -> int:
        return len(self.worker_ids) if self.worker_ids else 0
```

Use `${field_name}` interpolation for string composition. Use `@computed_field` for everything else such as boolean flags, numeric calculations, structural checks.

---

## Providers and Layering

### Built-in Providers

| Provider | Source |
|---|---|
| `FileProvider(path, watch=False)` | YAML, JSON, or TOML file |
| `EnvProvider(prefix, separator="_")` | Environment variables |
| `DotEnvProvider(path=".env")` | `.env` file → `os.environ` |
| `SSMProvider(path_prefix, region=None)` | AWS SSM Parameter Store |
| `VaultProvider(secret_path, url, token)` | HashiCorp Vault KV v2 |

Providers are applied in order. Later providers override earlier ones by default.

### Per-Provider Layering Rules

Control how specific fields are merged when a provider is applied:

```python
from layer import LayerRule

pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("base.yml"))
    .add_provider(
        EnvProvider("APP"),
        rules={
            "allowed_hosts":  LayerRule.APPEND,    # append to base list
            "feature_flags":  LayerRule.MERGE,     # merge with base dict
            "log_level":      LayerRule.PRESERVE,  # keep base value, ignore env
        }
    )
)
```

Available rules: `OVERRIDE` (default), `PRESERVE`, `MERGE` (dicts), `APPEND` (lists).

Dot-notation works for nested fields: `{"database.port": LayerRule.PRESERVE}`.

---

## Hot Reloading

```python
pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("config.yml", watch=True))
    .on_change("log_level", lambda field, old, new, shadow: reconfigure_logging(new))
    .on_change("database.host", lambda field, old, new, shadow: reconnect_db(new))
)
config = pipeline.load()
pipeline.start()  # starts background watchdog thread
```

Fields marked `reloadable=False` are locked at startup and skipped during reload (useful for parameters that can't safely change at runtime):

```python
@layerclass
class DBConfig:
    dsn: str       = field(str, default=None, reloadable=False)  # locked at startup
    pool_size: int = field(int, default=5)                        # can reload
```

---

## Custom Providers

```python
from layer.providers import BaseProvider

class RedisProvider(BaseProvider):
    def __init__(self, redis_client, key: str):
        self._client = redis_client
        self._key = key

    def read(self) -> dict:
        import json
        raw = self._client.get(self._key)
        return json.loads(raw) if raw else {}

    @property
    def source_name(self) -> str:
        return f"redis:{self._key}"
```

---

## Observability

### Pipeline Observer

```python
import logging
pipeline = ConfigPipeline(AppConfig, logger=logging.getLogger("myapp"))
```

Or subclass `BasePipelineObserver` for custom metrics:

```python
from layer import BasePipelineObserver

class DatadogObserver(BasePipelineObserver):
    def on_hot_reload_triggered(self, diffs):
        statsd.increment("config.reload", tags=[f"fields:{len(diffs)}"])

    def on_hot_reload_locked(self, field):
        statsd.increment("config.reload.locked", tags=[f"field:{field}"])

pipeline = ConfigPipeline(AppConfig, observer=DatadogObserver())
```

Available hooks: `on_provider_read`, `on_coercion_error`, `on_layer_merged`, `on_hot_reload_triggered`, `on_hot_reload_locked`.

---

## Exporters

Generate deployment artifacts directly from your schema:

```python
from layer import exporters

# .env template : descriptions become comments, secrets get placeholder values
print(exporters.to_dotenv_template(AppConfig, prefix="APP"))
# # Service hostname
# APP_HOST=localhost
# APP_PORT=8080
# APP_PASSWORD=<secret>

# Kubernetes ConfigMap : secrets automatically omitted
print(exporters.to_configmap(AppConfig, name="myapp-config"))

# JSON Schema for documentation or external validation
schema = exporters.to_json_schema(AppConfig)
```

---

## SolidifyMode

```python
from layer import SolidifyMode

pipeline = ConfigPipeline(AppConfig, mode=SolidifyMode.STRICT)
```

| Mode | Unknown keys | Type coercion errors |
|---|---|---|
| `LAX` | silently ignored | swallowed, raw value kept |
| `STANDARD` (default) | silently ignored | raises `CoercionError` |
| `STRICT` | raises `StructureError` | no coercion attempted |

---

## Direct Use (without Pipeline)

For simpler cases or testing:

```python
from layer import solidify, solidify_file, solidify_env

config = solidify_file("config.yml", AppConfig)
env_overlay = solidify_env("APP", AppConfig)
config.layer(env_overlay)
config.resolve()
config.validate(["prod"]).raise_if_invalid()
config.freeze()
```