"""Internal utilities for working with pydantic."""

from .base import Base, GQLBase, GQLId, SerializedToJson, Typename
from .v1_compat import (
    IS_PYDANTIC_V2,
    AliasChoices,
    computed_field,
    field_validator,
    model_validator,
)

__all__ = [
    "IS_PYDANTIC_V2",
    "Base",
    "GQLBase",
    "Typename",
    "GQLId",
    "SerializedToJson",
    "AliasChoices",
    "computed_field",
    "field_validator",
    "model_validator",
]
