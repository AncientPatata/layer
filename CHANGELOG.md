# Changelog

All notable changes to this project are documented automatically by [python-semantic-release](https://python-semantic-release.readthedocs.io/).

<!-- semantic-release will insert new entries above this line -->

## [0.1.0] — 2026-03-22

### Added

- `@layerclass` decorator for typed configuration schemas with `layer_obj` backward-compat alias
- `field()` with categorical validators, secrets, aliases, `env` override, and `reloadable` flag
- `@computed_field` for read-only derived properties integrated into `to_dict()` and `explain()`
- `@parser`, `@validator`, `@root_validator` class-level method decorators
- `ConfigPipeline` with ordered provider layering, per-provider `LayerRule` overrides, and hot-reload
- Built-in providers: `FileProvider` (YAML/JSON/TOML), `EnvProvider`, `DotEnvProvider`, `SSMProvider`, `VaultProvider`
- 14 single-field validators: `require`, `optional`, `not_empty`, `one_of`, `in_range`, `is_port`, `is_url`, `is_positive`, `regex`, `min_length`, `max_length`, `path_exists`, `instance_of`, `each_item`
- 5 cross-field validators: `requires_if`, `requires_any`, `requires_all`, `mutually_exclusive`, `depends_on`
- `${field_name}` and `${nested.path}` variable interpolation with circular reference detection
- Full source provenance tracking via `SourceHistory` — every field records its full value chain
- `SolidifyMode`: `LAX`, `STANDARD`, `STRICT` for controlling coercion strictness
- Exporters: `to_dotenv_template`, `to_configmap`, `to_json_schema`
- `BasePipelineObserver` with `LoggerObserver` for lifecycle metrics integration
- Exception hierarchy: `MissingDependencyError`, `HotReloadError`, `InterpolationCycleError`
- Type coercion for `Optional[T]`, `Union[A, B]`, `List[T]`, `Dict[K, V]`, `Literal[...]`, dataclasses, Pydantic v2
