"""Lightweight, solver-independent infrastructure for future learning studies.

No trained model or user-facing solver policy is provided by this package.
"""

from learning.features import (
    FEATURE_SCHEMA_NAME,
    FEATURE_SCHEMA_VERSION,
    extract_box_features,
    extract_instance_features,
    extract_type_features,
)

__all__ = [
    "FEATURE_SCHEMA_NAME",
    "FEATURE_SCHEMA_VERSION",
    "extract_box_features",
    "extract_instance_features",
    "extract_type_features",
]
