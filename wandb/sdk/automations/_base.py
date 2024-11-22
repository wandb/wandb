from __future__ import annotations

import sys
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, Json, ValidationError, WrapValidator
from pydantic.alias_generators import to_camel
from pydantic.main import IncEx
from pydantic_core import to_json
from pydantic_core.core_schema import ValidatorFunctionWrapHandler

if sys.version_info >= (3, 12):
    from typing import Annotated, override
else:
    from typing_extensions import Annotated, override


class Base(BaseModel):
    """Base class for all automation classes/types."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        validate_default=True,
        extra="forbid",
        alias_generator=to_camel,
        use_attribute_docstrings=True,
        from_attributes=True,
        revalidate_instances="always",
    )

    @override
    def model_dump(
        self,
        *,
        mode: Literal["json", "python"] | str = "json",  # NOTE: changed default
        include: IncEx | None = None,
        exclude: IncEx | None = None,
        context: dict[str, Any] | None = None,
        by_alias: bool = True,  # NOTE: changed default
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = True,  # NOTE: changed default
        round_trip: bool = True,  # NOTE: changed default
        warnings: bool | Literal["none", "warn", "error"] = True,
        serialize_as_any: bool = False,
    ) -> dict[str, Any]:
        return super().model_dump(
            mode=mode,
            include=include,
            exclude=exclude,
            context=context,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            round_trip=round_trip,
            warnings=warnings,
            serialize_as_any=serialize_as_any,
        )

    @override
    def model_dump_json(
        self,
        *,
        indent: int | None = None,
        include: IncEx | None = None,
        exclude: IncEx | None = None,
        context: dict[str, Any] | None = None,
        by_alias: bool = True,  # NOTE: changed default
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = True,  # NOTE: changed default
        round_trip: bool = True,  # NOTE: changed default
        warnings: bool | Literal["none", "warn", "error"] = True,
        serialize_as_any: bool = False,
    ) -> str:
        return super().model_dump_json(
            indent=indent,
            include=include,
            exclude=exclude,
            context=context,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            round_trip=round_trip,
            warnings=warnings,
            serialize_as_any=serialize_as_any,
        )


class GQLBase(Base):
    """Base class with extra customization for GQL generated types."""

    model_config = ConfigDict(
        extra="ignore",
        protected_namespaces=(),
    )


# ------------------------------------------------------------------------------
# Reusable annotations for field types
T = TypeVar("T")

Base64Id = Annotated[
    str,
    Field(repr=False, strict=True, frozen=True),
]

Typename = Annotated[
    T,
    Field(repr=False, alias="__typename", frozen=True),
]


def validate_maybe_json(v: Any, handler: ValidatorFunctionWrapHandler) -> Any:
    """Wraps default Json[...] field validator to allow instantiation with an already-decoded value."""
    try:
        return handler(v)
    except ValidationError:
        # Try revalidating after properly jsonifying the value
        return handler(to_json(v, by_alias=True, round_trip=True))


SerializedToJson = Annotated[
    Json[T],
    # Allow lenient instantiation/validation: incoming data may already be deserialized.
    WrapValidator(validate_maybe_json),
]
