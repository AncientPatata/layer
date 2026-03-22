"""
layer: A standalone package for deterministic, multi-source configuration
with categorical validation and layered merging.
"""

from .core import layer_obj, field, FieldDef, parser, validator, root_validator
from .solidify import solidify, solidify_env, solidify_file, write_file
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
)
from .interpolation import resolve_all, resolve_value, InterpolationError

__all__ = [
    # Core
    "layer_obj",
    "field",
    "FieldDef",
    "parser",
    "validator",
    "root_validator",
    # Solidification
    "solidify",
    "solidify_env",
    "solidify_file",
    "write_file",
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
    # Interpolation
    "resolve_all",
    "resolve_value",
    "InterpolationError",
]
