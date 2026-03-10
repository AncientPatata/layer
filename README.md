# Layer

## Overview

Layer is a standalone Python package for deterministic, multi-source configuration management. It is designed to handle complex application configurations by supporting categorical validation, layered merging, variable interpolation, and source history tracking.

It is well-suited for generic CLI tools, daemons, and applications that need to ingest configuration from multiple prioritized sources (e.g., default values, configuration files, environment variables, and command-line arguments) while maintaining strict type safety and explainability.

## Key Features

* **Schema Definition**: Define configuration structures using standard Python classes with type hinting and the `@layer_obj` decorator.
* **Multi-Source Ingestion**: Load configuration from YAML, JSON, TOML files, environment variables, or standard Python dictionaries.
* **Layered Merging**: Combine multiple configuration layers with granular merging rules (`OVERRIDE`, `PRESERVE`, `MERGE`, `APPEND`).
* **Categorical Validation**: Group validation rules into categories (e.g., `cli`, `server`, `common`) to run specific checks based on the current execution context.
* **Cross-Field Validation**: Enforce complex logic between fields (e.g., `requires_if`, `mutually_exclusive`, `depends_on`).
* **Source Tracking & Explainability**: Track the exact source of every configuration value (e.g., "config.yml", "env:APP_PORT", "default") and generate structured reports of the configuration state.
* **Variable Interpolation**: Reference fields within strings (e.g., `${database.host}`) and resolve them dynamically.
* **JSON Schema Generation**: Automatically generate draft-07 JSON Schemas from your configuration definitions.
* **Secret Redaction**: Mask sensitive configuration values in logs and exports.

## Installation

Assuming the package is available in your Python environment:

```bash
pip install layer

```

*Note: File-specific loaders may require optional dependencies (e.g., `PyYAML` for YAML support, `tomli` for TOML support on Python < 3.11).*

## Quick Start

### 1. Defining the Schema

Use the `@layer_obj` decorator and `field` function to define your configuration structure.

```python
from layer import layer_obj, field
from layer.validation import require, one_of, in_range, is_url

@layer_obj
class DatabaseConfig:
    host: str = field(str, default="localhost", description="Database hostname")
    port: int = field(int, in_range(1, 65535), default=5432, description="Database port")
    password: str = field(str, secret=True, default=None)

@layer_obj
class AppConfig:
    # Requires an endpoint if the 'server' validation category is invoked
    endpoint: str = field(str, server=[require, is_url], default="http://${database.host}:${database.port}")
    environment: str = field(str, common=[one_of("dev", "prod")], default="dev")
    database: DatabaseConfig = field(DatabaseConfig)

```

### 2. Loading Configuration

You can instantiate the configuration directly, or load it from various sources using the `solidify` module.

```python
from layer import solidify_file, solidify_env

# Load from a YAML file
file_config = solidify_file("config.yml", AppConfig, source="config.yml")

# Load from Environment Variables (e.g., APP_ENVIRONMENT=prod, APP_DATABASE_PORT=5433)
env_config = solidify_env(prefix="APP", target=AppConfig)

```

### 3. Layering Configuration

To combine configurations, use the `.layer()` method. This merges values based on their source, typically allowing later layers (like environment variables or CLI flags) to override earlier ones (like files).

```python
from layer import LayerRule

# Create a base configuration
app_config = AppConfig()

# Layer file configuration on top
app_config.layer(file_config)

# Layer environment variables on top of that
app_config.layer(env_config)

# Custom layering rules can be applied (e.g., preserving base values or appending to lists)
# app_config.layer(other_config, rules={"database.port": LayerRule.PRESERVE})

```

### 4. Interpolation

Once all layers are merged, resolve any variable references (like `${database.host}`).

```python
app_config.resolve()

```

### 5. Validation

Run validation checks against specific categories.

```python
# Check 'common' rules and 'server' rules
result = app_config.validate(categories=["common", "server"])

if not result.is_valid:
    for error in result.errors:
        print(f"Error in {error.field}: {error.message}")
    # Or simply raise an exception
    # result.raise_if_invalid()

```

### 6. Explainability and Exporting

The `explain()` method provides a structured breakdown of the configuration, showing the current value, type, description, and the exact source layer that provided the value.

```python
import json

# Explain outputs a list of dictionaries with field metadata. Secrets are redacted by default.
explanation = app_config.explain(redact=True)
print(json.dumps(explanation, indent=2))

# Export the flattened configuration to a standard dictionary
config_dict = app_config.to_dict(redact=False)

```

## Advanced Usage

### Cross-Field Validation

Layer supports complex validators that evaluate the state of multiple fields simultaneously.

```python
from layer.validation import requires_if, mutually_exclusive, depends_on

@layer_obj
class AuthConfig:
    auth_type: str = field(str, default="none", common=[one_of("none", "token", "cert")])
    token: str = field(str, default=None, common=[requires_if("auth_type", "token")])
    cert_path: str = field(str, default=None, common=[depends_on("key_path")])
    key_path: str = field(str, default=None)

```

### Diffing Configurations

You can compare two configuration objects of the same type to find differences, which is useful for generating execution plans or audit logs.

```python
diffs = old_config.diff(new_config)
for diff in diffs:
    print(f"{diff['field']} changed from {diff['old_value']} to {diff['new_value']}")

```

### Freezing State

Once configuration loading and interpolation are complete, you can freeze the object to prevent accidental runtime mutations.

```python
app_config.freeze()

# This will now raise an AttributeError
# app_config.environment = "staging" 

```
