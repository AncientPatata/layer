# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Layer is a Python library for deterministic, multi-source configuration management. It provides a decorator-based system (`@layer_obj`) for defining typed configuration schemas that support layered merging from multiple sources (files, env vars, dicts), categorical validation, variable interpolation, and full source history tracking.

## Commands

```bash
# Run all tests
uv run --with pytest pytest

# Run a single test file
uv run --with pytest pytest tests/test_solidify.py

# Run a single test
uv run --with pytest pytest tests/test_solidify.py::TestTypeCoercion::test_str_to_int

# Install in development mode (enables plain `pytest` after)
uv pip install -e ".[dev]"

# Lint
ruff check src/

# Build
hatchling build
```

## Architecture

The intended data flow for configuration objects is: **Schema Definition → Source Loading → Layering → Interpolation → Validation → Freeze/Export**.

Key modules in `src/layer/`:

- **`core.py`** — The `@layer_obj` decorator and `field()` function. The decorator transforms a class into a configuration object with methods like `.layer()`, `.validate()`, `.resolve()`, `.freeze()`, `.explain()`, `.to_dict()`, `.diff()`, `.json_schema()`. This is the central module that ties everything together.
- **`solidify.py`** — Loading untyped data into typed `@layer_obj` instances. `solidify()` handles dicts, `solidify_file()` handles YAML/JSON/TOML files, `solidify_env()` handles environment variables with prefix conventions. Includes type coercion logic (str → int, bool, float, list, dict).
- **`validation.py`** — 14 single-field validators (e.g., `require`, `one_of`, `in_range`, `regex`) and 5 cross-field validators (e.g., `requires_if`, `mutually_exclusive`, `depends_on`). Validators follow the signature `(value, field_name, config) -> True | raise ValidationError`. Validation is organized by category so different rule sets run in different contexts.
- **`interpolation.py`** — Resolves `${field_name}` and `${nested.path}` variable references in string values, with circular reference detection.
- **`layering.py`** — `LayerRule` enum: OVERRIDE (default), PRESERVE, MERGE (dicts), APPEND (lists).
- **`sources.py`** — `SourceHistory` and `SourceEntry` dataclasses for tracking which source set each field value.
- **`exceptions.py`** — Exception hierarchy: `ConfigError` → `ValidationError`, `StructureError`, `LayeringError`, `InterpolationError`.

## Key Design Details

- `field()` returns a `FieldDef` storing type hints, defaults, validators (grouped by category), metadata, description, secret flag, and custom parser.
- The `@layer_obj` decorator adds `_field_defs`, `_sources`, and `_frozen` to instances. It replaces `FieldDef` class attributes with their default values on instantiation.
- Tests use a custom harness with global `passed`/`failed` counters (not pytest). The test file runs directly with `python test_features.py` and exits with code 1 on failure.
- Python >= 3.10.12 required. Uses UV as package manager.
