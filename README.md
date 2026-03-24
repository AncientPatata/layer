<div align="center">

# Layer
[![CI](https://github.com/ancientpatata/layer/actions/workflows/ci.yml/badge.svg)](https://github.com/ancientpatata/layer/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/layerconf.svg)](https://pypi.org/project/layerconf/)
[![Python versions](https://img.shields.io/pypi/pyversions/layerconf.svg)](https://pypi.org/project/layerconf/)
[![Docs](https://img.shields.io/badge/docs-mkdocs-blue)](https://ancientpatata.github.io/layer/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/ancientpatata/layer/blob/main/LICENSE)

**Deterministic, multi-source configuration with validation, provenance tracking, and hot-reloading.**

</div>



Layer is a Python library for applications that pull config from multiple places (files, environment variables, AWS SSM, HashiCorp Vault, etc.) and need to merge them reliably, validate them explicitly, and understand exactly where every value came from.

`load()` never validates. `validate()` never loads. The result is a typed, frozen, thread-safe object where every field knows which provider set it and what the value was before.



---

## Installation

```bash
pip install layerconf

# Optional providers
pip install layerconf[watch]   # FileProvider(watch=True) hot-reload via watchdog
pip install layerconf[dotenv]  # EnvProvider(env_file=".env") support
pip install layerconf[aws]     # SSMProvider via boto3
pip install layerconf[vault]   # VaultProvider via hvac
pip install layerconf[etcd]    # EtcdProvider via etcd3
```

---

## Quick Start

```python
from layer import layerclass, field, ConfigPipeline, require, is_port
from layer.providers import FileProvider, EnvProvider

@layerclass
class AppConfig:
    host:        str = field(str, default="localhost")
    port:        int = field(int, default=8080, prod=[require, is_port])
    timeout_ms:  int = field(int, default=5000)
    db_password: str = field(str, default=None, secret=True)

pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("config.yml"))
    .add_provider(EnvProvider("APP"))           # APP_HOST, APP_PORT, etc. win over file
)

config = pipeline.load()                        # ingest → merge → resolve → freeze
pipeline.validate(["prod"]).raise_if_invalid()  # explicit, never inside load()

print(config.source_of("host"))   # "env:APP_HOST", "config.yml", or "default"
```

---

## Provenance Tracking

Every field records where its value came from. Useful when something is wrong and you need to know which of your five providers is responsible.

```python
config.source_of("host")
# "env:APP_HOST"

config.source_history_of("host")
# [
#   SourceEntry(source="default",      value="localhost"),
#   SourceEntry(source="config.yml",   value="db.internal"),
#   SourceEntry(source="env:APP_HOST", value="db.prod.example.com"),
# ]

config.explain()
# [
#   {"field": "host",        "value": "db.prod.example.com", "source": "env:APP_HOST", ...},
#   {"field": "port",        "value": 5432,                  "source": "config.yml",   ...},
#   {"field": "db_password", "value": "***",                 "source": "env:APP_...",  ...},
# ]
```

`explain()` redacts `secret=True` fields by default. `to_dict()` defaults to no redaction since it's typically used for serialization — pass `redact=True` explicitly when using it for logging or display.

When you set a field programmatically, you can tag the source for full traceability:

```python
config.set("database.host", "db-failover.internal", source="failover-handler")
config.source_of("database.host")   # "failover-handler"
```

---

## Nested Configs and Interpolation

Nest `@layerclass` instances as typed fields. `${...}` interpolation resolves across the full tree using dot-paths, after all providers have been merged.

```python
@layerclass
class DatabaseConfig:
    host: str = field(str, default="localhost")
    port: int = field(int, default=5432)
    name: str = field(str, default="myapp")

@layerclass
class AppConfig:
    database: DatabaseConfig = field(DatabaseConfig, default=None)
    dsn: str = field(str, default="postgresql://${database.host}:${database.port}/${database.name}")
```

Dot-notation works everywhere: `config.get("database.host")`, `on_change("database.host", cb)`, `LayerRule` overrides in `add_provider()`.

---

## Validation

### Categories

Attach validators to named categories. Only the categories you request are checked. Bare (uncategorized) validators always run.

```python
@layerclass
class DBConfig:
    host:     str = field(str, default="localhost")
    port:     int = field(int, is_port, default=5432)       # bare — always runs
    ssl_cert: str = field(str, default=None,
                          prod=[require, path_exists],       # only in prod
                          dev=[optional])
    password: str = field(str, default=None,
                          prod=[require],
                          secret=True)
```

```python
pipeline.validate(["prod"]).raise_if_invalid()   # prod rules + bare
pipeline.validate([]).raise_if_invalid()         # bare only
pipeline.validate("*").raise_if_invalid()        # every category + bare

# Validate specific fields only
pipeline.validate(["prod"], fields=["ssl_cert", "password"]).raise_if_invalid()
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
| `optional` | always passes (documents that `None` is intentional) |
| `one_of("a", "b")` | value is in the given set |
| `in_range(lo, hi)` | numeric value within `[lo, hi]` |
| `is_port` | integer in `1–65535` |
| `is_url` | starts with `http://` or `https://` |
| `is_positive` | numeric value `> 0` |
| `regex(pattern)` | string matches the regex |
| `min_length(n)` / `max_length(n)` | string/list length |
| `path_exists` | path exists on the filesystem |
| `each_item(validator)` | applies any validator to every list item |
| `requires_if("other", value)` | this field is `None` when `other == value` |
| `requires_any("a", "b", ...)` | all listed fields are `None` |
| `mutually_exclusive("a", "b", ...)` | more than one listed field is set |
| `depends_on("a", "b", ...)` | this field is set but a dependency is `None` |

### Custom Validators

Any callable `(value, field_name, config) -> True | raise ValidationError`. The `config` argument gives access to the full object, so cross-field checks are straightforward:

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

For checks that need `self` or span multiple fields, use `@validator` and `@root_validator`:

```python
from layer import validator, root_validator, ValidationError, ConfigError

@layerclass
class TLSConfig:
    cert_path: str = field(str, default=None)
    key_path:  str = field(str, default=None)

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

## Parsers

Parsers transform a field's value during loading, separate from validation. By default they run after type coercion; pass `before_coerce=True` when you need to clean a raw string before `int()` or similar is called.

```python
from layer import parser

@layerclass
class PaymentConfig:
    amount_cents: int = field(int, default=0)
    endpoint:     str = field(str, default=None)

    @parser("amount_cents", before_coerce=True)
    def _clean_amount(self, value):
        """Strip currency symbols before int() is called."""
        if isinstance(value, str):
            return value.strip().lstrip("$€£").replace(",", "")
        return value

    @parser("endpoint")
    def _normalize_endpoint(self, value):
        """Trim and remove trailing slashes after coercion."""
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return value
```

---

## Providers and Layering

### Built-in Providers

| Provider | Source |
|---|---|
| `FileProvider(path, watch=False, required=True)` | YAML, JSON, or TOML file |
| `EnvProvider(prefix, env_file=None)` | Environment variables and `.env` files |
| `SSMProvider(path_prefix)` | AWS SSM Parameter Store |
| `VaultProvider(secret_path, url, token)` | HashiCorp Vault KV v2 |
| `EtcdProvider(prefix, host, port)` | Etcd cluster |

Providers are applied in order. Later providers override earlier ones by default.

### Layering Rules

Control how specific fields are merged per provider:

```python
from layer import LayerRule

pipeline.add_provider(
    FileProvider(str(home_dir / ".mycli/config.toml"), required=False),
    rules={
        "plugins":       LayerRule.APPEND,    # append to existing list
        "feature_flags": LayerRule.MERGE,     # union with existing dict
        "log_level":     LayerRule.PRESERVE,  # keep the first value set
    }
)
```

Available rules: `OVERRIDE` (default), `PRESERVE`, `MERGE` (dicts), `APPEND` (lists). Dot-notation works for nested fields: `{"database.port": LayerRule.PRESERVE}`.

### Custom Providers

```python
from layer.providers import BaseProvider

class RedisProvider(BaseProvider):
    def __init__(self, redis_client, key: str):
        self._client = redis_client
        self._key = key

    def read(self) -> dict:
        raw = self._client.get(self._key)
        return json.loads(raw) if raw else {}

    @property
    def source_name(self) -> str:
        return f"redis:{self._key}"
```

Any `BaseProvider` can be used for polling remote sources (KV stores, S3, feature flag APIs). Call `pipeline._reload()` on a timer to pull changes without file watching.

---

## Hot Reloading

```python
pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("config.yml", watch=True))
    .on_change("log_level",     lambda field, old, new, shadow: reconfigure_logging(new))
    .on_change("database.host", lambda field, old, new, shadow: reconnect_db(new))
)
config = pipeline.load()
pipeline.start()   # starts background watchdog thread
```

Fields marked `reloadable=False` are locked to their startup value and skipped on reload:

```python
@layerclass
class DBConfig:
    dsn:       str = field(str, default=None, reloadable=False)  # locked at startup
    pool_size: int = field(int, default=5)                       # reloads freely
```

---

## Computed Fields

`@computed_field` exposes a method as a read-only property. It's evaluated on every access and appears in `to_dict()` and `explain()`.

```python
@layerclass
class WorkerConfig:
    worker_ids: list = field(list, default=None)

    @computed_field
    def worker_count(self) -> int:
        """Number of active workers."""
        return len(self.worker_ids) if self.worker_ids else 0
```

---

## Aliases and Field Options

Fields accept `alias` and `aliases` to map external key names (camelCase, kebab-case, etc.) to your Python field names:

```python
@layerclass
class APIConfig:
    api_key:  str = field(str, default=None, secret=True,  alias="apiKey")
    base_url: str = field(str, default=None, aliases=["baseUrl", "base-url"])
    port:     int = field(int, default=8080, env="SERVICE_PORT")  # explicit env var name
```

`to_dict(by_alias=True)` exports using alias names — useful when serializing back to a format that expects camelCase.

---

## Observability

### Pipeline Observer

```python
import logging
pipeline = ConfigPipeline(AppConfig, logger=logging.getLogger("myapp"))
```

Or subclass `BasePipelineObserver` for custom metrics/alerting:

```python
from layer import BasePipelineObserver

class DatadogObserver(BasePipelineObserver):
    def on_hot_reload_triggered(self, diffs):
        statsd.increment("config.reload", tags=[f"fields:{len(diffs)}"])

    def on_hot_reload_locked(self, field):
        # A reloadable=False field changed — may need a restart
        alert.warning(f"Locked config field '{field}' changed; restart required")

pipeline = ConfigPipeline(AppConfig, observer=DatadogObserver())
```

Available hooks: `on_provider_read`, `on_coercion_error`, `on_layer_merged`, `on_hot_reload_triggered`, `on_hot_reload_locked`.

### Exporters

Generate deployment artifacts directly from your schema:

```python
from layer import exporters

# .env template — field descriptions become comments, secrets get a placeholder
exporters.to_dotenv_template(AppConfig, prefix="APP")
# # Service hostname
# APP_HOST=localhost
# APP_PORT=8080
# APP_DB_PASSWORD=<secret>

# Kubernetes ConfigMap — secrets omitted with a comment
exporters.to_configmap(AppConfig, name="myapp-config")

# JSON Schema for documentation or external validation
schema = exporters.to_json_schema(AppConfig)
```

---

## SolidifyMode

Controls how provider data is coerced into your schema:

| Mode | Unknown keys | Type coercion errors |
|---|---|---|
| `LAX` | silently ignored | swallowed, raw value kept |
| `STANDARD` (default) | silently ignored | raises `CoercionError` |
| `STRICT` | raises `StructureError` | no coercion attempted |

```python
pipeline = ConfigPipeline(AppConfig, mode=SolidifyMode.STRICT)
```

---

## Without a Pipeline

For scripts, tests, or one-off validation:

```python
from layer import solidify_file, solidify_env

config = solidify_file("config.yml", AppConfig)
env_overlay = solidify_env("APP", AppConfig)
config.layer(env_overlay)
config.resolve()
config.validate(["prod"]).raise_if_invalid()
config.freeze()
```

---

## Links

- [Documentation](https://ancientpatata.github.io/layer/)
- [Getting Started](https://ancientpatata.github.io/layer/getting-started/)

--- 

<div align="center">

Made with ❤️ 

</div>
