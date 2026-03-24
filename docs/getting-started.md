# Getting Started

## The Problem Layer Solves

Your application reads config from a base YAML file, with local overrides in a second file, and production secrets injected as environment variables. Without a structured pipeline, you end up with `os.getenv()` scattered through your code, `dict.update()` calls that silently clobber each other, and no way to answer: *why does this field have this value right now?*

Layer solves this by giving you a typed pipeline with a defined merge order, full provenance tracking on every field, and validation that runs explicitly when you ask for it.

## Installation

```bash
pip install layerconf
```

Optional extras for specific providers:

```bash
pip install layerconf[watch]   # hot-reload via watchdog
pip install layerconf[dotenv]  # EnvProvider(.env) support
pip install layerconf[aws]     # SSMProvider (boto3)
pip install layerconf[vault]   # VaultProvider (hvac)
```

## Define a Schema

Use `@layerclass` to declare your config as a typed class. Each field is declared with `field()`, which takes a type hint, a default, and any validation rules or metadata you want to attach.

```python
from layer import layerclass, field, require, is_port

@layerclass
class AppConfig:
    host: str     = field(str,  default="localhost",  description="Service hostname")
    port: int     = field(int,  default=8080,         prod=[require, is_port])
    workers: int  = field(int,  default=4)
    debug: bool   = field(bool, default=False)
```

`description` is used as a comment when generating `.env` templates. Validation rules attached to `prod=` only run when you call `validate(["prod"])`. More on both of these later.

Layer can also handle `secret=True` fields that are automatically redacted in logs and `explain()` output, and `alias=` / `aliases=` for mapping external key names to your Python field names:

```python
@layerclass
class APIConfig:
    api_key:  str = field(str, default=None, secret=True,   alias="apiKey")
    base_url: str = field(str, default=None, aliases=["baseUrl", "base-url"])
```

With `alias="apiKey"`, a YAML/JSON file that contains `apiKey: abc123` will be correctly mapped to `api_key`. The `aliases` list provides additional fallback names tried in order. Field names are always normalized: `base-url` and `baseUrl` both map to `base_url`.

## Build a Pipeline

`ConfigPipeline` is the primary interface. You add providers in priority order — later providers override earlier ones — and call `load()` to ingest everything.

```python
from layer import ConfigPipeline
from layer.providers import FileProvider, EnvProvider

pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("config/default.yml"))   # baseline
    .add_provider(FileProvider("config/local.yml", required=False))  # local dev overrides
    .add_provider(EnvProvider("APP_", env_file=".env")) # APP_HOST, APP_PORT, etc. from .env or system env
)

config = pipeline.load()
```

`add_provider()` returns `self`, so the fluent chaining style above is natural. You can also build the pipeline incrementally:

```python
pipeline = ConfigPipeline(AppConfig)
pipeline.add_provider(FileProvider("config/default.yml"))
if os.path.exists("config/local.yml"):
    pipeline.add_provider(FileProvider("config/local.yml"))
pipeline.add_provider(EnvProvider("APP_", env_file=".env"))

config = pipeline.load()
```

`load()` reads all providers, merges their outputs in order, resolves `${variable}` references, and freezes the config. It never validates — that is always a separate, explicit step.

## Understand Where Values Came From

After `load()`, every field knows exactly where its value came from. This is one of the most useful things Layer does, and it's worth checking before you wire up validation.

```python
config.source_of("host")
# "env:APP_HOST"  — came from the environment variable

config.source_of("port")
# "config/default.yml"  — no env var set, fell back to the file

config.source_of("workers")
# "default"  — no source set it, using the field default
```

For the full picture of every field at once:

```python
config.explain()
# [
#   {"field": "host",    "value": "api.prod.example.com", "source": "env:APP_HOST",          ...},
#   {"field": "port",    "value": 8080,                   "source": "config/default.yml",    ...},
#   {"field": "workers", "value": 4,                      "source": "default",               ...},
#   {"field": "api_key", "value": "***",                  "source": "env:APP_API_KEY",        ...},
# ]
```

Note that `api_key` is automatically redacted because it was declared with `secret=True`. `explain()` redacts secrets by default since it's a debugging tool — pass `redact=False` if you need the real value. `to_dict()` is the inverse: it defaults to `redact=False` because it's commonly used for serialization, so pass `redact=True` explicitly when using it for logging or display.

`explain()` also accepts `full_history=True` to show the complete chain of every source that contributed to each field — useful when you suspect a value was set and then overridden unexpectedly.

You can also access and set fields by dot-notation string, which is useful for nested configs and programmatic access:

```python
config.get("database.host")             # nested field access
config.set("database.host", "db2.internal", source="migration-script")
config.source_of("database.host")       # "migration-script"
```

`set()` also accepts `strict=True` to immediately validate the new value against that field's rules before writing it.

## Validate

Validation is always an explicit step, separate from loading. Pass a list of category names to run only those validators. Bare (uncategorized) validators always run regardless of what categories you request.

```python
# Run prod rules + all bare validators
pipeline.validate(["prod"]).raise_if_invalid()

# Run bare validators only
pipeline.validate([]).raise_if_invalid()

# Run every registered category
pipeline.validate("*").raise_if_invalid()
```

You can also validate specific fields rather than the whole config — useful in hot-reload callbacks or after a `set()` call:

```python
pipeline.validate(["prod"], fields=["port", "host"]).raise_if_invalid()
```

See the full [Validation](validation.md) guide for built-in validators, cross-field rules, and custom validators.

## Next Steps

- [Concepts](concepts.md) — the layering engine, type coercion, and categorical validation in depth
- [Providers](providers.md) — FileProvider, EnvProvider, SSM, Vault, hot-reloading, and custom providers
- [Validation](validation.md) — all built-in validators, cross-field rules, parsers, and custom validators
- [Observability](observability.md) — provenance, diffing, pipeline observers, and export artifacts