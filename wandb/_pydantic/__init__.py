"""Internal utilities for working with pydantic."""

__all__ = [
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

from pydantic import (
    AliasChoices,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from .base import CompatBaseModel, GQLBase, GQLInput, GQLResult, JsonableModel
from .field_types import GQLId, Typename
from .pagination import Connection, ConnectionWithTotal, Edge, PageInfo
from .utils import from_json, gql_typename, pydantic_isinstance, to_json
