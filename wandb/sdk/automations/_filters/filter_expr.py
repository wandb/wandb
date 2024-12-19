"""Pydantic-compatible representations of MongoDB expressions (e.g. for queries, filtering, aggregation)."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import Any, Dict, Union

from pydantic import Discriminator, GetCoreSchemaHandler, RootModel, Tag
from pydantic._internal import _repr
from pydantic.main import IncEx
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function, str_schema

from .filter_ops import (
    And,
    Contains,
    Eq,
    Gt,
    Gte,
    In,
    Lt,
    Lte,
    Ne,
    Nor,
    Not,
    NotIn,
    Op,
    Or,
    Regex,
    Scalar,
)

if sys.version_info >= (3, 12):
    from typing import Annotated, Literal, override
else:
    from typing_extensions import Annotated, Literal, override


# ------------------------------------------------------------------------------
class FilteredField(str):
    """A field name in a MongoDB query expression that identifies which field the criteria is evaluated on."""

    def __hash__(self) -> int:
        # Needed to avoid `TypeError: unhashable type: 'FilteredField'` on validation
        return super().__hash__()

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        # See: https://docs.pydantic.dev/latest/concepts/json_schema/#skipjsonschema-annotation
        return no_info_after_validator_function(
            cls._validate,
            str_schema(),
        )

    @classmethod
    def _validate(cls, obj: Any) -> str:
        if isinstance(obj, str):
            return str(obj)
        raise TypeError(f"Unknown type {type(obj).__name__!r}")

    # ------------------------------------------------------------------------------
    def lt(self, other: Scalar) -> FilterExpr:
        return self.__lt__(other)

    def gt(self, other: Scalar) -> FilterExpr:
        return self.__gt__(other)

    def lte(self, other: Scalar) -> FilterExpr:
        return self.__le__(other)

    def gte(self, other: Scalar) -> FilterExpr:
        return self.__ge__(other)

    def ne(self, other: Scalar) -> FilterExpr:
        return self.__ne__(other)

    def eq(self, other: Scalar) -> FilterExpr:
        return self.__eq__(other)

    def in_(self, other: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr({self: In(other=other)})

    def not_in(self, other: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr({self: NotIn(other=other)})

    def regex_match(self, other: str) -> FilterExpr:
        return FilterExpr({self: Regex(other=other)})

    def contains(self, other: str) -> FilterExpr:
        return FilterExpr({self: Contains(other=other)})

    # ------------------------------------------------------------------------------
    def __lt__(self, other: Scalar) -> FilterExpr:  # type: ignore[override,misc]
        return FilterExpr({self: Lt(other=other)})

    def __gt__(self, other: Scalar) -> FilterExpr:  # type: ignore[override,misc]
        return FilterExpr({self: Gt(other=other)})

    def __le__(self, other: Scalar) -> FilterExpr:  # type: ignore[override,misc]
        return FilterExpr({self: Lte(other=other)})

    def __ge__(self, other: Scalar) -> FilterExpr:  # type: ignore[override,misc]
        return FilterExpr({self: Gte(other=other)})

    def __eq__(self, other: Scalar) -> FilterExpr:  # type: ignore[override]
        return FilterExpr({self: Eq(other=other)})

    def __ne__(self, other: Scalar) -> FilterExpr:  # type: ignore[override]
        return FilterExpr({self: Ne(other=other)})


# ------------------------------------------------------------------------------
class FilterExpr(RootModel[Dict[FilteredField, "AnyOp"]]):
    root: dict[FilteredField, AnyOp]

    def __repr_args__(self) -> _repr.ReprArgs:
        yield from self.root.items()

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
        exclude_none: bool = False,
        round_trip: bool = True,  # NOTE: changed default
        warnings: bool | Literal["none", "warn", "error"] = True,
        serialize_as_any: bool = False,
    ) -> dict[str, Any]:
        return super().model_dump(  # type: ignore[no-any-return]
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
        exclude_none: bool = False,
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

    def __and__(self, other: AnyExpr) -> FilterExpr:
        raise NotImplementedError

    def __or__(self, other: AnyExpr) -> FilterExpr:
        raise NotImplementedError

    def __invert__(self) -> FilterExpr:
        raise NotImplementedError


def get_op_tag(obj: Any) -> Any:
    """Return the discriminator tag to identify the Op type in a tagged union."""
    if isinstance(obj, dict):
        possible_keys = [k for k in obj.keys() if k.startswith("$")]
        try:
            [op_key] = possible_keys
        except ValueError:
            return None
        else:
            return op_key

    if isinstance(obj, Op):
        return obj.OP

    return None


AnyOp = Annotated[
    Union[
        Annotated[And, Tag(And.OP)],
        Annotated[Or, Tag(Or.OP)],
        Annotated[Nor, Tag(Nor.OP)],
        Annotated[Not, Tag(Not.OP)],
        # ------------------------------------------------------------------------------
        Annotated[Lt, Tag(Lt.OP)],
        Annotated[Gt, Tag(Gt.OP)],
        Annotated[Lte, Tag(Lte.OP)],
        Annotated[Gte, Tag(Gte.OP)],
        Annotated[Eq, Tag(Eq.OP)],
        Annotated[Ne, Tag(Ne.OP)],
        # ------------------------------------------------------------------------------
        Annotated[In, Tag(In.OP)],
        Annotated[NotIn, Tag(NotIn.OP)],
        # ------------------------------------------------------------------------------
        Annotated[Regex, Tag(Regex.OP)],
        Annotated[Contains, Tag(Contains.OP)],
    ],
    Discriminator(get_op_tag),
]

AnyExpr = Union[
    AnyOp,
    FilterExpr,
]
