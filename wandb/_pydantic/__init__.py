"""Internal utilities for working with pydantic."""

__all__ = [
    "IS_PYDANTIC_V2",
    "CompatBaseModel",
    "JsonableModel",
    "GQLBase",
    "GQLInput",
    "GQLResult",
    "Connection",
    "ConnectionWithTotal",
    "Edge",
    "PageInfo",
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
    "ValidationError",
]

# Available in all supported Pydantic versions.
from pydantic import ValidationError

from .base import CompatBaseModel, GQLBase, GQLInput, GQLResult, JsonableModel
from .field_types import GQLId, Typename
from .pagination import Connection, ConnectionWithTotal, Edge, PageInfo
from .utils import IS_PYDANTIC_V2, from_json, gql_typename, pydantic_isinstance, to_json
from .v1_compat import (
    AliasChoices,
    computed_field,
    field_validator,
    model_validator,
    to_camel,
)
