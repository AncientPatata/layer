# Observability

## Provenance Tracking

Imagine a value is wrong in production. Is it coming from the YAML file, an environment variable, or SSM? With Layer, you don't have to guess.

Every field records the full history of every source that contributed to its value. The active source is always one method call away:

```python
config.source_of("database.host")
# "env:APP_DATABASE_HOST"
```

Dot-notation works for nested fields. Common source values you'll see:

- `"default"` — the field default, no provider set it
- `"config/base.yml"` — set by a file provider (the file path is the source name)
- `"env:APP_DATABASE_HOST"` — set by an environment variable
- `"/myapp/prod/"` — set by an SSM provider (the path prefix is the source name)
- `"set()"` — set via `config.set()`, or the custom source string you passed

When you call `config.set()` explicitly, you can tag the source yourself for full traceability:

```python
config.set("database.host", "db-failover.internal", source="failover-handler")
config.source_of("database.host")
# "failover-handler"
```

### Full Source History

`source_of()` returns the current (winning) source. `source_history_of()` returns the full chain of every value that was applied to the field across all providers:

```python
config.source_history_of("database.host")
# [
#   SourceEntry(source="default",              value="localhost"),
#   SourceEntry(source="config/base.yml",      value="db.internal"),
#   SourceEntry(source="env:APP_DATABASE_HOST", value="db.prod.example.com"),
# ]
```

This is useful when you're debugging a value that was set by multiple providers and you want to understand the full override chain, not just the winner.

## `explain()` and `diff()`

### `.explain()`

Provides a structured overview of every field — current value, source, type, description, and validation categories. Secret fields are automatically redacted:

```python
config.explain()
# [
#   {"field": "host",     "value": "db.prod.example.com", "source": "env:APP_HOST",   ...},
#   {"field": "port",     "value": 5432,                  "source": "config.yml",     ...},
#   {"field": "password", "value": "***",                 "source": "env:APP_PASSWORD",...},
#   {"field": "dsn",      "value": "***",                 "source": "computed",       ...},
# ]
```

Pass `full_history=True` to include the complete source chain for every field — the same data as `source_history_of()`, but for all fields at once. Pass `redact=False` if you need the real values in a trusted context (audit tooling, debug CLIs).

### `.diff()`

Compares two config instances and returns a structured list of what changed and where each value came from:

```python
before = pipeline.load()
# ... some time passes, a file changes ...
after = pipeline._build_shadow()

for change in before.diff(after):
    print(change)
# {"field": "database.host", "old_value": "db-1", "new_value": "db-2",
#  "old_source": "config.yml", "new_source": "config.yml"}
```

`diff()` is used internally by the hot-reload engine, but it's equally useful in deployment tooling — you can diff a current production config against a proposed new config before applying it, and log or alert on specific fields that changed.

## Pipeline Observers

Attach an observer to get structured events from the full load and reload lifecycle. The simplest setup uses the built-in `LoggerObserver`:

```python
import logging
pipeline = ConfigPipeline(AppConfig, logger=logging.getLogger("myapp"))
# Emits debug/info/warning log messages for provider reads, merges, reloads, and locked fields
```

For custom integration — pushing metrics to Datadog, Prometheus counters, alerting on locked-field violations — subclass `BasePipelineObserver`:

```python
from layer import BasePipelineObserver

class MetricsObserver(BasePipelineObserver):
    def on_hot_reload_triggered(self, diffs):
        statsd.increment("config.reload", tags=[f"changes:{len(diffs)}"])

    def on_hot_reload_locked(self, field):
        # A reloadable=False field changed in the file but was skipped
        statsd.increment("config.reload.locked", tags=[f"field:{field}"])
        alert.warning(f"Config field '{field}' changed but is locked — requires restart")

    def on_provider_read(self, provider_name, data):
        statsd.increment("config.provider.read", tags=[f"provider:{provider_name}"])

    def on_coercion_error(self, field, value, target_type, error):
        statsd.increment("config.coercion.error", tags=[f"field:{field}"])

pipeline = ConfigPipeline(AppConfig, observer=MetricsObserver())
```

Available hooks: `on_provider_read`, `on_coercion_error`, `on_layer_merged`, `on_hot_reload_triggered`, `on_hot_reload_locked`.

Use `LoggerObserver` when structured logs are sufficient. Use a custom observer when you need to integrate with an external metrics or alerting system, or when `on_hot_reload_locked` events should trigger an operational alert (a locked field changing in the config file is a signal that a restart may be needed).

## Exporters

Exporters generate deployment artifacts from a `@layerclass` schema definition — no loaded instance required. They read your field definitions, defaults, descriptions, and secret flags to produce files that other tools and people can use.

```python
from layer import exporters
```

### `.env` Template

Generates a `.env`-style template suitable for onboarding new developers or documenting what environment variables your application expects. Field `description` values become inline comments, so this is also why writing descriptions on your fields pays off. Secret fields get a `<secret>` placeholder instead of the default value.

```python
@layerclass
class AppConfig:
    host:    str = field(str, default="localhost",  description="Service hostname")
    port:    int = field(int, default=8080,         description="Listening port")
    api_key: str = field(str, default=None,         secret=True)

print(exporters.to_dotenv_template(AppConfig, prefix="APP"))
```

Output:

```
# Service hostname
APP_HOST=localhost
# Listening port
APP_PORT=8080
APP_API_KEY=<secret>
```

### Kubernetes ConfigMap

Generates a `ConfigMap` YAML string. Numeric defaults are quoted to preserve their string type; secret fields are omitted with a comment pointing to Kubernetes Secrets.

```python
print(exporters.to_configmap(AppConfig, name="myapp-config"))
```

Output:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: myapp-config
data:
  HOST: localhost
  PORT: "8080"
  # API_KEY: <omitted — use a Secret resource>
```

### JSON Schema

Returns a JSON Schema dict (draft-07). Useful for editor completion support, external config validation, or publishing a machine-readable contract for your application's configuration.

```python
schema = exporters.to_json_schema(AppConfig)
# {
#   "$schema": "http://json-schema.org/draft-07/schema#",
#   "title": "AppConfig",
#   "type": "object",
#   "properties": { ... },
#   "required": [...]
# }
```