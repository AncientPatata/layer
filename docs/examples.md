# Examples

## Example 1: Tracking Down a Wrong Value

You've deployed and a field has an unexpected value. Layer makes this a one-liner to diagnose.

```python
from layer import layerclass, field, ConfigPipeline, require, is_url
from layer.providers import FileProvider, EnvProvider, SSMProvider

@layerclass
class AppConfig:
    api_url:     str = field(str, default=None, prod=[require, is_url])
    timeout_ms:  int = field(int, default=5000)
    db_password: str = field(str, default=None, secret=True)

pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("config/base.yml"))
    .add_provider(SSMProvider("/myapp/prod/"))
    .add_provider(EnvProvider("APP"))
)

config = pipeline.load()

# Something is wrong with api_url — where did it come from?
print(config.source_of("api_url"))
# "/myapp/prod/"  ← SSM is overriding the file value

# See the full chain of every source that touched it
print(config.source_history_of("api_url"))
# [
#   SourceEntry(source="default",        value=None),
#   SourceEntry(source="config/base.yml", value="https://api.staging.example.com"),
#   SourceEntry(source="/myapp/prod/",    value="https://api.prod.example.com"),
# ]

# Get a full picture of everything at once (secrets redacted automatically)
for entry in config.explain():
    print(f"{entry['field']:20} {entry['value']:40} ← {entry['source']}")
```

The `explain()` output shows every field, its current value, and exactly which provider set it. `db_password` shows `***` automatically because it was declared with `secret=True`.

---

## Example 2: Plugin Lists That Accumulate

A CLI tool where a system config defines base plugins and a user config adds personal ones. Without `LayerRule.APPEND`, the user config would clobber the system list entirely.

```python
from pathlib import Path
from layer import layerclass, field, ConfigPipeline, LayerRule
from layer.providers import FileProvider, EnvProvider

@layerclass
class CLIConfig:
    api_key:       str  = field(str,  default=None, secret=True, alias="apiKey")
    output_format: str  = field(str,  default="text", aliases=["outputFormat", "output-format"])
    plugins:       list = field(list, default=[])

def load_cli_config() -> CLIConfig:
    home_dir = Path.home()

    pipeline = (
        ConfigPipeline(CLIConfig)
        # 1. System-wide defaults
        .add_provider(FileProvider("/etc/mycli/config.toml", required=False))

        # 2. User config — plugins APPEND rather than replace
        .add_provider(
            FileProvider(str(home_dir / ".mycli" / "config.toml"), required=False),
            rules={"plugins": LayerRule.APPEND}
        )

        # 3. Environment variables (also handles MYCLI_API_KEY, MYCLI_OUTPUT_FORMAT)
        .add_provider(EnvProvider("MYCLI"))
    )

    config = pipeline.load()
    pipeline.validate([]).raise_if_invalid()
    return config

config = load_cli_config()
# If /etc/mycli/config.toml has plugins: [core-logger]
# and ~/.mycli/config.toml has plugins: [my-formatter]
# then config.plugins == ["core-logger", "my-formatter"]
```

The `alias="apiKey"` on `api_key` means a config file using camelCase (`apiKey: abc123`) is handled correctly without any manual mapping. `aliases=["outputFormat", "output-format"]` lets users write the field in whatever style they prefer.

---

## Example 3: Different Validation Strictness per Environment

One schema, three validation contexts. The rules live with the schema, not scattered through application startup code.

```python
import os
from layer import layerclass, field, ConfigPipeline, require, is_url, is_port, path_exists, in_range, one_of
from layer.providers import FileProvider, EnvProvider, SSMProvider

@layerclass
class ServiceConfig:
    host:          str = field(str,  default="localhost")

    # is_port is bare — runs in every environment
    port:          int = field(int,  is_port, default=8080,
                               staging=[require],
                               prod=[require])

    external_api:  str = field(str,  default=None,
                               staging=[require, is_url],
                               prod=[require, is_url])

    ssl_cert_path: str = field(str,  default=None,
                               prod=[require, path_exists])

    connect_timeout_ms: int = field(int, default=5000,
                                    prod=[in_range(100, 3000)])

    debug:         bool = field(bool, default=True,
                                prod=[one_of(False)])

def load_config() -> ServiceConfig:
    env_tier = os.environ.get("ENV_TIER", "local")

    pipeline = (
        ConfigPipeline(ServiceConfig)
        .add_provider(FileProvider("config/base.yml"))
        .add_provider(FileProvider(f"config/{env_tier}.yml", required=False))
        .add_provider(SSMProvider(f"/service/{env_tier}/", ) if env_tier != "local" else None)
        .add_provider(EnvProvider("SERVICE"))
    )

    # add_provider ignores None, so the SSMProvider line above is safe
    config = pipeline.load()

    # Run only the rules for this environment
    pipeline.validate([env_tier]).raise_if_invalid()
    return config
```

In `local`, only `is_port` (bare) runs. In `staging`, `port` and `external_api` are required. In `prod`, `debug` must be `False`, `ssl_cert_path` must exist on disk, and `connect_timeout_ms` is capped at 3 seconds. None of this requires an `if env_tier == "prod"` branch.

---

## Example 4: Hot Reload with Locked Fields and `on_change` Callbacks

A long-running service where `log_level` and `rate_limit` should update live, but `database_dsn` must never change after startup (the connection pool was already opened with it).

```python
import logging
from layer import layerclass, field, ConfigPipeline
from layer.providers import FileProvider

@layerclass
class WorkerConfig:
    database_dsn: str = field(str, default=None, reloadable=False)  # locked at startup
    log_level:    str = field(str, default="INFO")                  # reloads freely
    rate_limit:   int = field(int, default=100)                     # reloads freely

def reconfigure_logging(new_level: str):
    logging.getLogger().setLevel(getattr(logging, new_level, logging.INFO))
    logging.info("Log level changed to %s", new_level)

def update_rate_limiter(new_limit: int):
    rate_limiter.set_limit(new_limit)
    logging.info("Rate limit updated to %d req/s", new_limit)

pipeline = (
    ConfigPipeline(WorkerConfig)
    .add_provider(FileProvider("config/worker.yml", watch=True))
    .on_change("log_level",  lambda field, old, new, shadow: reconfigure_logging(new))
    .on_change("rate_limit", lambda field, old, new, shadow: update_rate_limiter(new))
)

config = pipeline.load()
pipeline.start()   # background watchdog thread begins watching config/worker.yml

# If the file changes:
# - log_level and rate_limit are updated and callbacks fire
# - database_dsn is skipped with a warning (reloadable=False)
```

If `database_dsn` changes in the file, Layer emits a warning log and skips the update. The field retains its startup value. This is the correct behavior — the value changed, and the warning is a signal that a restart may be needed to pick it up.

For remote sources, pair `_reload()` with a polling thread instead of `watch=True`. See [Providers → Polling Remote Providers](providers.md) for the pattern.

---

## Example 5: Parsing and Normalizing Raw Input

A payment service that receives amount values in various human-formatted strings from config files, and needs them as clean integers before validation runs.

```python
from layer import layerclass, field, parser, ConfigPipeline, require, is_positive
from layer.providers import FileProvider, EnvProvider

@layerclass
class PaymentConfig:
    # Raw input might be "1,500", "$1500", "1.500,00" (European)
    min_amount_cents: int = field(int, is_positive, default=100, prod=[require])
    max_amount_cents: int = field(int, is_positive, default=100000, prod=[require])

    # External API sends "apiEndpoint" in its config exports
    api_endpoint: str = field(str, default=None, alias="apiEndpoint", prod=[require])

    @parser("min_amount_cents", "max_amount_cents", before_coerce=True)
    def _clean_amount(self, value):
        """Strip currency symbols and separators before int() is called."""
        if isinstance(value, str):
            return value.strip().lstrip("$€£").replace(",", "")
        return value

    @parser("api_endpoint")
    def _normalize_endpoint(self, value):
        """Remove trailing slashes after coercion — value is already a str here."""
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return value

pipeline = (
    ConfigPipeline(PaymentConfig)
    .add_provider(FileProvider("config/payments.yml"))
    .add_provider(EnvProvider("PAYMENT"))
)

config = pipeline.load()
# config/payments.yml had: min_amount_cents: "1,500"
# before_coerce=True → "1500" → int coercion → 1500

pipeline.validate(["prod"]).raise_if_invalid()
```

`_clean_amount` uses `before_coerce=True` because it needs to strip the comma *before* `int()` is called — `int("1,500")` would raise a `CoercionError`. `_normalize_endpoint` runs after coercion (the default) since the value is already a string and just needs trimming.