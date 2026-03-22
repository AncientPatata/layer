"""
layer: A standalone package for deterministic, multi-source configuration
with categorical validation and layered merging.
"""

from . import exporters
from .core import (
    FieldDef,
    computed_field,
    field,
    layer_obj,  # backward-compat alias
    layerclass,
    parser,
    root_validator,
    validator,
)
from .exceptions import (
    CoercionError,
    ConfigError,
    HotReloadError,
    InterpolationCycleError,
    LayeringError,
    MissingDependencyError,
    StructureError,
    ValidationError,
)
from .interpolation import InterpolationError, resolve_all, resolve_value
from .layering import LayerRule
from .observers import BasePipelineObserver, LoggerObserver
from .pipeline import ConfigPipeline
from .providers import BaseProvider
from .solidify import SolidifyMode, solidify, solidify_env, solidify_file, write_file
from .validation import (
    depends_on,
    each_item,
    in_range,
    instance_of,
    is_port,
    is_positive,
    is_url,
    max_length,
    min_length,
    mutually_exclusive,
    not_empty,
    one_of,
    optional,
    path_exists,
    regex,
    require,
    requires_all,
    requires_any,
    requires_if,
)

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
