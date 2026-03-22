# Concepts

## Layering Order Is Everything

The central idea in Layer is that configuration sources form a stack. You add providers in a specific order, and later providers override values set by earlier ones. The result is deterministic and explicit.

```python
pipeline = (
    ConfigPipeline(AppConfig)
    .add_provider(FileProvider("config/defaults.yml"))   # lowest priority
    .add_provider(FileProvider("config/local.yml"))      # overrides defaults
    .add_provider(EnvProvider("APP"))                    # highest priority
)
```

When `load()` runs, it reads each provider in order and applies its values on top of what's already there. If `config/defaults.yml` sets `host: localhost` and `APP_HOST=api.internal` is in the environment, the environment wins — because it was added last.

This sounds simple, but it's the thing that most config setups get wrong in subtle ways. Layer makes the priority order part of the code, not something you have to infer.

### Layering Rules

The default merge strategy is `OVERRIDE` — the incoming value replaces whatever was there. For some fields, that's wrong. A list of plugins, or a dict of feature flags, should accumulate across sources rather than be clobbered.

Pass `rules=` to `add_provider()` to change the strategy for specific fields:

```python
from layer import LayerRule

pipeline.add_provider(
    FileProvider(str(home_dir / ".mycli" / "config.toml"), required=False),
    rules={
        "plugins":       LayerRule.APPEND,    # append to the existing list
        "feature_flags": LayerRule.MERGE,     # merge into the existing dict
        "log_level":     LayerRule.PRESERVE,  # keep whatever was set first
    }
)
```

`APPEND` is for lists that should accumulate (plugins, allowed hosts, extra headers). `MERGE` is for dicts where you want the union of all keys, with later sources winning on conflicts. `PRESERVE` is for fields that should be locked once set by any source — useful when you want a "first write wins" rather than "last write wins" approach.

For nested `@layerclass` fields, you can pass a nested rules dict:

```python
rules={"database": {"host": LayerRule.PRESERVE}}
```

## Type Coercion

Environment variables are always strings. Layer coerces them into your declared types automatically when it reads a provider.

```python
@layerclass
class Config:
    port:         int             = field(int,        default=8080)
    debug:        bool            = field(bool,       default=False)
    timeout_ms:   float           = field(float,      default=5000.0)
    allowed_envs: List[str]       = field(List[str],  default=[])
    limits:       Dict[str, int]  = field(Dict[str, int], default={})
```

Given environment variables:

```
APP_PORT=3000
APP_DEBUG=true
APP_ALLOWED_ENVS=prod,staging,dev
APP_LIMITS=web=100,worker=50
```

Layer resolves these to:

```python
config.port          # 3000          (int)
config.debug         # True          (bool — "true"/"1"/"yes" are all truthy)
config.allowed_envs  # ["prod", "staging", "dev"]   (List[str] from comma-separated)
config.limits        # {"web": 100, "worker": 50}   (Dict[str, int] from key=value pairs)
```

JSON-formatted values also work: `APP_ALLOWED_ENVS=["prod","staging"]` is parsed via `json.loads` first, then falls back to comma-splitting.

Layer also handles `Optional[T]`, `Union[A, B]` (tries each type in order), `Literal["a", "b"]` (validates the value is in the allowed set), and nested dataclasses or Pydantic models (a dict is passed to the constructor).

### Parsers

Parsers are pre-processing transforms that run on a field's value before type coercion is applied. They exist because loading and validation are separate concerns — sometimes you need to normalize raw input before it's even ready to validate.

A parser is a method decorated with `@parser("field_name")`:

```python
from layer import layerclass, field, parser

@layerclass
class PaymentConfig:
    # Raw value might be "1.234.567" (European formatting) or " $1,234 "
    amount_cents: int = field(int, default=0)

    @parser("amount_cents")
    def _clean_amount(self, value):
        if isinstance(value, str):
            # Strip currency symbols, spaces, and thousands separators
            return value.strip().lstrip("$€").replace(",", "").replace(".", "")
        return value
```

Parsers run during `solidify()`, `solidify_env()`, and `set()` — anywhere a value is written to a field. They receive the raw value and must return the transformed value. If parsing fails, raise a `ValueError` or `ConfigError` with a clear message.

You can register one parser method for multiple fields:

```python
@parser("endpoint", "callback_url")
def _normalize_url(self, value):
    if isinstance(value, str):
        return value.strip().rstrip("/")
    return value
```

The key distinction from validators: parsers transform, validators assert. A parser that strips whitespace from a URL is different from a validator that checks the URL is reachable. Keep them separate.

## Categorical Validation

This is Layer's most distinctive feature, and it's worth understanding the motivation before the mechanics.

Suppose you have a `cert_path` field that must exist in production but is irrelevant in local development. The naive approach:

```python
if os.environ.get("ENV") == "production":
    assert config.cert_path is not None
```

This works, but as your config grows, these checks scatter through your codebase. The rules for what's valid in production are no longer visible when you look at the schema.

Layer's alternative: attach the rules to the field, named by category:

```python
@layerclass
class ServerConfig:
    host:      str = field(str,  default="localhost")
    port:      int = field(int,  default=8080,  prod=[require, is_port])
    cert_path: str = field(str,  default=None,  prod=[require, path_exists])
    debug:     bool = field(bool, default=False, prod=[one_of(False)])
```

Then at your application entry point, you pass the environment tier:

```python
env_tier = os.environ.get("ENV_TIER", "dev")
pipeline.validate([env_tier]).raise_if_invalid()
```

In production, `validate(["prod"])` checks that `port` is a valid port, `cert_path` exists on disk, and `debug` is `False`. In development, none of those rules run. The schema is the single source of truth for what's required where.

### Bare validators

Validators attached directly to `field()` — outside any category — always run, regardless of which categories you request:

```python
port: int = field(int, is_port, default=8080)
# is_port runs on every validate() call
```

### Multiple categories

A field can have rules in several categories simultaneously:

```python
timeout_ms: int = field(
    int,
    is_positive,                               # bare — always runs
    default=5000,
    staging=[in_range(1000, 30000)],           # only in staging
    prod=[require, in_range(100, 10000)],      # only in prod
)
```

### Running categories

```python
pipeline.validate(["prod"])           # prod rules + bare
pipeline.validate(["prod", "audit"])  # prod + audit rules + bare
pipeline.validate([])                 # bare only
pipeline.validate("*")                # every registered category + bare
```

You can also validate specific fields rather than the whole schema, which is useful after a `set()` call or in a hot-reload callback:

```python
pipeline.validate("*", fields=["port", "cert_path"]).raise_if_invalid()
```

## Variable Interpolation

Field values can reference other fields using `${field_name}` syntax. References are resolved after all providers have been merged, so the interpolated value reflects whichever source ultimately won.

```yaml
# config.yml
base_url: "api.example.com"
endpoint: "https://${base_url}/v1/status"
health_check: "${endpoint}/health"
```

Dot-notation works for nested fields:

```yaml
database:
  host: "db.internal"
  port: 5432

connection_string: "postgresql://${database.host}:${database.port}/mydb"
```

Layer detects circular references (`a → b → a`) and raises `InterpolationCycleError` rather than hanging.

## The Pipeline Lifecycle

When you call `pipeline.load()`, four things happen in sequence:

1. Each provider is read and its data is coerced into a typed overlay matching your schema.
2. Each overlay is layered onto the live config using that provider's rules.
3. All `${variable}` references are resolved.
4. The config is frozen — no further mutation is possible without an explicit `set()` or hot-reload.

Validation never happens inside `load()`. This separation is intentional: you can load a minimal config quickly, pass it around, and defer expensive cross-field checks to the moment they matter. It also means loading can succeed in environments where some fields legitimately aren't set yet.