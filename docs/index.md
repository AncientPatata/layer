# Layer

**Deterministic, multi-source configuration with validation, provenance tracking, and hot-reloading.**

Most applications pull config from several places — a base YAML file, environment variable overrides, a secrets manager in production. Layer gives you a typed pipeline that merges all of them in a defined order, lets you ask *where did this value come from?* at any time, and validates with different rule sets per environment. The result is a frozen, thread-safe object with no surprises.

## Highlights

| Feature | Description |
|---|---|
| **Multi-source merging** | Add providers in priority order — files, env vars, SSM, Vault, or anything custom |
| **Provenance tracking** | Every field records its full source history; `source_of()` and `explain()` make debugging instant |
| **Categorical validation** | Run different rule sets per environment (`prod` vs `dev`) without branching logic |
| **Variable interpolation** | `${field_name}` and `${nested.path}` resolved across the full config tree |
| **Type coercion** | `str → int/bool/float/List[T]/Dict[K,V]`, `Optional[T]`, `Union`, `Literal` — from env vars or files |
| **Parsers** | Pre-coercion transforms per field (strip whitespace, remove formatting characters, normalize paths) |
| **Computed fields** | Read-only derived properties included in `to_dict()` and `explain()` |
| **Hot reloading** | Live config updates without restart; `reloadable=False` locks critical fields |
| **Secret redaction** | `secret=True` fields are automatically masked in `explain()` and logs |
| **Aliases** | Map external key names (e.g. `apiKey`) to your Python field names |
| **Export artifacts** | `.env` templates, Kubernetes ConfigMaps, JSON Schema |
| **Freeze & thread safety** | `freeze()` locks the config object for safe concurrent reads |

## Quick Example

```python
from layer import layerclass, field, ConfigPipeline, require, is_port
from layer.providers import FileProvider, EnvProvider

@layerclass
class AppConfig:
    host: str = field(str, default="localhost", description="Service hostname")
    port: int = field(int, default=8080, prod=[require, is_port])
    db_password: str = field(str, default=None, secret=True)

pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("config.yml"))
    .add_provider(EnvProvider("APP"))      # APP_HOST, APP_PORT, APP_DB_PASSWORD
)

config = pipeline.load()
pipeline.validate(["prod"]).raise_if_invalid()

print(config.host)
print(config.source_of("host"))   # "env:APP_HOST" or "config.yml" or "default"
```

See [Getting Started](getting-started.md) for the full walkthrough.