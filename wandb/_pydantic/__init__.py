"""Internal utilities for working with pydantic."""

from .base import CompatBaseModel, GQLBase
from .field_types import UNSET, GQLId, SerializedToJson, Typename
from .utils import (
    IS_PYDANTIC_V2,
    ensure_json,
    from_json,
    gql_typename,
    pydantic_isinstance,
    to_json,
)
from .v1_compat import (
    AliasChoices,
    computed_field,
    field_validator,
    model_validator,
    to_camel,
)

__all__ = [
    "IS_PYDANTIC_V2",
    "CompatBaseModel",
    "GQLBase",
    "UNSET",
    "Typename",
    "GQLId",
    "SerializedToJson",
    "AliasChoices",
    "computed_field",
    "field_validator",
    "model_validator",
    "pydantic_isinstance",
    "to_camel",
    "to_json",
    "from_json",
    "ensure_json",
    "gql_typename",
]
