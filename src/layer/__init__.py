"""
layer: A standalone package for deterministic, multi-source configuration
with categorical validation and layered merging.
"""

from .core import (
    layerclass,
    layer_obj,  # backward-compat alias
    field,
    FieldDef,
    parser,
    validator,
    root_validator,
    computed_field,
)
from .solidify import solidify, solidify_env, solidify_file, write_file, SolidifyMode
from .layering import LayerRule
from .validation import (
    require,
    optional,
    one_of,
    in_range,
    path_exists,
    instance_of,
    min_length,
    regex,
    max_length,
    not_empty,
    is_url,
    is_positive,
    is_port,
    each_item,
    requires_if,
    requires_any,
    requires_all,
    mutually_exclusive,
    depends_on,
)
from .exceptions import (
    ConfigError,
    ValidationError,
    StructureError,
    LayeringError,
    CoercionError,
    InterpolationCycleError,
    MissingDependencyError,
    HotReloadError,
)
from .interpolation import resolve_all, resolve_value, InterpolationError
from .pipeline import ConfigPipeline
from .providers import BaseProvider
from .observers import BasePipelineObserver, LoggerObserver
from . import exporters

__all__ = [
    # Core
    "layerclass",
    "layer_obj",  # backward-compat alias
    "field",
    "FieldDef",
    "parser",
    "validator",
    "root_validator",
    "computed_field",
    # Solidification
    "solidify",
    "solidify_env",
    "solidify_file",
    "write_file",
    "SolidifyMode",
    # Layering
    "LayerRule",
    # Validators — single-field
    "require",
    "optional",
    "one_of",
    "in_range",
    "path_exists",
    "instance_of",
    "min_length",
    "regex",
    "max_length",
    "not_empty",
    "is_url",
    "is_positive",
    "is_port",
    "each_item",
    # Validators — cross-field
    "requires_if",
    "requires_any",
    "requires_all",
    "mutually_exclusive",
    "depends_on",
    # Exceptions
    "ConfigError",
    "ValidationError",
    "StructureError",
    "LayeringError",
    "CoercionError",
    "InterpolationError",
    "InterpolationCycleError",
    "MissingDependencyError",
    "HotReloadError",
    # Interpolation
    "resolve_all",
    "resolve_value",
    # Pipeline
    "ConfigPipeline",
    "BaseProvider",
    # Observers
    "BasePipelineObserver",
    "LoggerObserver",
    # Exporters module
    "exporters",
]
