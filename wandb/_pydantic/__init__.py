"""Internal utilities for working with pydantic."""

from .base import (
    Base,
    CompatBaseModel,
    GQLBase,
    GQLId,
    SerializedToJson,
    Typename,
    ensure_json,
)
from .utils import IS_PYDANTIC_V2, pydantic_isinstance, to_json
from .v1_compat import AliasChoices, computed_field, field_validator, model_validator

__all__ = [
    "IS_PYDANTIC_V2",
    "CompatBaseModel",
    "Base",
    "GQLBase",
    "Typename",
    "GQLId",
    "SerializedToJson",
    "AliasChoices",
    "computed_field",
    "field_validator",
    "model_validator",
    "pydantic_isinstance",
    "to_json",
    "ensure_json",
]
