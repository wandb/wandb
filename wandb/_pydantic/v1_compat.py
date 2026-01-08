"""Pydantic v2 helpers and decorators.

NOTE: This module is retained for backward compatibility with existing imports.
It previously provided Pydantic v1 compatibility shims that are no longer needed.
"""

from __future__ import annotations

from pydantic import AliasChoices, computed_field, field_validator, model_validator
from pydantic.alias_generators import to_camel

__all__ = [
    "AliasChoices",
    "computed_field",
    "field_validator",
    "model_validator",
    "to_camel",
]
