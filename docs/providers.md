# Providers

Providers are the data sources Layer reads from to build your configuration. They are added to a `ConfigPipeline` in priority order — later providers override values set by earlier ones.

## Building a Pipeline

The standard way to use Layer is with `ConfigPipeline`:

```python
from layer import ConfigPipeline
from layer.providers import FileProvider, EnvProvider, SSMProvider

pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("config/base.yml"))          # global baseline
    .add_provider(FileProvider("config/local.yml",          # local dev overrides
                               required=False))
    .add_provider(SSMProvider("/myapp/prod/"))              # secrets from AWS SSM
    .add_provider(EnvProvider("APP"))                       # env vars win over everything
)

config = pipeline.load()
```

`add_provider()` returns `self`, so fluent chaining is natural. The order you add providers is the order they are applied — last one wins by default.

A practical ordering strategy that works for most applications:

1. Global defaults (a committed base YAML)
2. Environment-specific overrides (a `config/prod.yml` selected at startup)
3. Remote secrets (SSM, Vault)
4. Local overrides and environment variables (highest priority, for per-deployment or per-developer settings)

### Without a Pipeline

For scripts, tests, or one-off validation, you can bypass `ConfigPipeline` entirely and work with the config object directly:

```python
from layer import solidify_file, solidify_env

config = solidify_file("config.yml", AppConfig)
env_overlay = solidify_env("APP", AppConfig)
config.layer(env_overlay)
config.resolve()
config.validate(["worker_node"]).raise_if_invalid()
config.freeze()
```

This is the same sequence `ConfigPipeline.load()` runs internally. It's more verbose but gives you fine-grained control, which is useful in test fixtures where you want to construct configs with specific values without touching files.

## Built-in Providers

### FileProvider

Reads YAML, JSON, or TOML files. Format is auto-detected from the extension.

```python
FileProvider("config.yml")                         # YAML
FileProvider("config.json")                        # JSON
FileProvider("config.toml")                        # TOML
FileProvider("config.yml", required=False)         # silently ignored if missing
FileProvider("config.yml", watch=True)             # enable hot-reload (requires layer[watch])
```

### EnvProvider

Reads environment variables with a given prefix. `APP_HOST` maps to `host`, `APP_DATABASE_PORT` maps to `database_port` (or the nested field `database.port` if your schema has a nested `@layerclass`).

```python
EnvProvider("APP")                    # APP_HOST → host, APP_PORT → port
EnvProvider("APP", separator="__")    # APP__DATABASE__HOST → database.host
```

### DotEnvProvider

Reads a `.env` file and injects its variables into `os.environ`. Chain it with `EnvProvider` so prefix-stripping is handled consistently. Requires `pip install layerconf[dotenv]`.

```python
from layer.providers import DotEnvProvider, EnvProvider

pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(DotEnvProvider(".env"))
    .add_provider(EnvProvider("APP"))
)
```

### SSMProvider

Reads all parameters under an AWS SSM path prefix. Requires `pip install layerconf[aws]`.

```python
from layer.providers import SSMProvider

SSMProvider("/myapp/prod/")
# /myapp/prod/database_host  →  database_host
# /myapp/prod/api_key        →  api_key
```

### VaultProvider

Reads a KV v2 secret from HashiCorp Vault. Requires `pip install layerconf[vault]`.

```python
from layer.providers import VaultProvider

VaultProvider(
    secret_path="myapp/config",
    url="https://vault.example.com",
    token="s.abc123"
)
```

## Layering Rules

Pass `rules=` to `add_provider()` to override the merge strategy for specific fields:

```python
from layer import LayerRule

pipeline.add_provider(
    FileProvider(str(home_dir / ".mycli" / "config.toml"), required=False),
    rules={
        "plugins":       LayerRule.APPEND,    # append to existing list, not replace
        "feature_flags": LayerRule.MERGE,     # union the dict, don't clobber it
        "api_url":       LayerRule.PRESERVE,  # lock to the first value set
    }
)
```

`APPEND` is the most commonly useful rule. Without it, a user's local `plugins: [my-plugin]` would wipe out the system-level `plugins: [core-plugin]` rather than extending it. With `APPEND`, both lists are concatenated.

`MERGE` is for dicts where you want later sources to add or update individual keys without removing keys that the earlier source set. Useful for feature flag maps, header dicts, and similar key-value collections.

`PRESERVE` means "the first source to set this field wins." Useful when you want an environment variable to set a value that no later provider (including defaults) should be able to change.

## Hot Reloading

Layer supports live config updates without restarting your application. When a watched provider detects a change, the pipeline rebuilds a shadow config, diffs it against the live config, fires any registered callbacks, and atomically applies the changes. Fields marked `reloadable=False` are never updated.

Requires `pip install layerconf[watch]`.

```python
pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("config.yml", watch=True))
    .on_change("log_level", lambda field, old, new, shadow: reconfigure_logging(new))
    .on_change("pool_size",  lambda field, old, new, shadow: db_pool.resize(new))
)

config = pipeline.load()
pipeline.start()   # starts a background watchdog thread
```

`on_change` callbacks receive the field name, old value, new value, and the full shadow config (so you can read other fields if the update requires cross-field context). Common use cases:

- **`log_level`** — call `logging.getLogger().setLevel(new)` to change log verbosity at runtime without a restart.
- **`pool_size`** — resize a database connection pool when the file changes.
- **`rate_limit`** — update an in-memory rate limiter threshold.

### Polling Remote Providers

File watching via `watchdog` covers local files, but providers don't have to be files. Any `BaseProvider` can be polled: a remote KV store, an S3 object, a feature flag API. If you're polling a remote source, the typical pattern is to add a provider that fetches on every `read()` call and wrap it with a periodic reload:

```python
import threading

def start_polling(pipeline, interval_seconds=30):
    def _poll():
        while True:
            time.sleep(interval_seconds)
            pipeline._reload()
    t = threading.Thread(target=_poll, daemon=True)
    t.start()

pipeline = ConfigPipeline(AppConfig).add_provider(RedisConfigProvider(redis_client, "app:config"))
config = pipeline.load()
start_polling(pipeline, interval_seconds=30)
```

On each poll, `_reload()` re-reads all providers, diffs the result against the live config, and applies only what changed.

### `reloadable=False`

Fields marked `reloadable=False` are locked to their startup value. If a reload detects a change to a locked field, it is silently skipped and a warning is emitted.

```python
@layerclass
class DBConfig:
    dsn:       str = field(str, default=None, reloadable=False)  # locked at startup
    pool_size: int = field(int, default=5)                       # reloads freely
```

`reloadable=False` is appropriate for fields where a mid-run change would be dangerous or meaningless — database DSNs (the connection pool was already opened with the original value), TLS certificate paths (the cert was already loaded), or any field whose value is consumed once at startup.

## Custom Providers

Any class that extends `BaseProvider` and implements `read()` and `source_name` is a valid provider. Layer calls `read()` every time it needs to ingest that source, including during hot-reload polling.

```python
from layer.providers import BaseProvider

class RedisConfigProvider(BaseProvider):
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

Use it like any built-in provider:

```python
pipeline.add_provider(RedisConfigProvider(redis_client, "app:config"))
```

For a polling-style remote provider, keep `read()` stateless — it will be called repeatedly, and each call should return the current state of the remote source.