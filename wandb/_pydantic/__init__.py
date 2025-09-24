"""Internal utilities for working with pydantic."""

__all__ = [
    "IS_PYDANTIC_V2",
    "CompatBaseModel",
    "JsonableModel",
    "GQLBase",
    "Typename",
    "GQLId",
    "AliasChoices",
    "computed_field",
    "field_validator",
    "model_validator",
    "pydantic_isinstance",
    "to_camel",
    "to_json",
    "from_json",
    "gql_typename",
]

from .base import CompatBaseModel, GQLBase, JsonableModel
from .field_types import GQLId, Typename
from .utils import IS_PYDANTIC_V2, from_json, gql_typename, pydantic_isinstance, to_json
from .v1_compat import (
    AliasChoices,
    computed_field,
    field_validator,
    model_validator,
    to_camel,
)
