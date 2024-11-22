"""Pydantic-compatible representations of MongoDB expressions (e.g. for queries, filtering, aggregation)."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Dict, Union

from pydantic import Discriminator, GetCoreSchemaHandler, RootModel, Tag
from pydantic._internal import _repr
from pydantic.main import IncEx
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function, str_schema

from wandb.sdk.automations._filters.comparison import (
    Eq,
    Gt,
    Gte,
    In,
    Lt,
    Lte,
    Ne,
    NotIn,
)
from wandb.sdk.automations._filters.evaluation import Contains, Regex
from wandb.sdk.automations._filters.logic import And, Nor, Not, Or
from wandb.sdk.automations._filters.utils import get_op_tag

if TYPE_CHECKING:
    from wandb.sdk.automations._filters.comparison import ValueT

if sys.version_info >= (3, 12):
    from typing import Annotated, Literal, override
else:
    from typing_extensions import Annotated, Literal, override


# ------------------------------------------------------------------------------
class FilterableField(str):
    """A field name in a MongoDB query expression that identifies which field the criteria is evaluated on."""

    def __hash__(self) -> int:
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
        # TODO: Handle if we're passed a class attribute, e.g. Artifact.tags
        if isinstance(obj, str):
            return str(obj)

        raise TypeError(f"Unknown type {type(obj).__name__!r}")

    # ------------------------------------------------------------------------------
    def lt(self, value: ValueT) -> FilterExpression:
        return self.__lt__(value)

    def gt(self, value: ValueT) -> FilterExpression:
        return self.__gt__(value)

    def lte(self, value: ValueT) -> FilterExpression:
        return self.__le__(value)

    def gte(self, value: ValueT) -> FilterExpression:
        return self.__ge__(value)

    def ne(self, value: ValueT) -> FilterExpression:
        return self.__ne__(value)

    def eq(self, value: ValueT) -> FilterExpression:
        return self.__eq__(value)

    def in_(self, values: Iterable[ValueT]) -> FilterExpression:
        return FilterExpression.model_validate({self: In(inner_operand=values)})

    def not_in(self, values: Iterable[ValueT]) -> FilterExpression:
        return FilterExpression.model_validate({self: NotIn(inner_operand=values)})

    def regex_match(self, pattern: str) -> FilterExpression:
        return FilterExpression.model_validate({self: Regex(inner_operand=pattern)})

    # ------------------------------------------------------------------------------
    def __lt__(self, value: ValueT) -> FilterExpression:  # type: ignore[override,misc]
        return FilterExpression.model_validate({self: Lt(inner_operand=value)})

    def __gt__(self, value: ValueT) -> FilterExpression:  # type: ignore[override,misc]
        return FilterExpression.model_validate({self: Gt(inner_operand=value)})

    def __le__(self, value: ValueT) -> FilterExpression:  # type: ignore[override,misc]
        return FilterExpression.model_validate({self: Lte(inner_operand=value)})

    def __ge__(self, value: ValueT) -> FilterExpression:  # type: ignore[override,misc]
        return FilterExpression.model_validate({self: Gte(inner_operand=value)})

    def __eq__(self, value: ValueT) -> FilterExpression:  # type: ignore[override]
        return FilterExpression.model_validate({self: Eq(inner_operand=value)})

    def __ne__(self, value: ValueT) -> FilterExpression:  # type: ignore[override]
        return FilterExpression.model_validate({self: Ne(inner_operand=value)})


# ------------------------------------------------------------------------------
class FilterExpression(RootModel[Dict[FilterableField, "AnyOp"]]):
    root: dict[FilterableField, AnyOp]

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

    def __and__(self, other: AnyExpr) -> FilterExpression:
        raise NotImplementedError

    def __or__(self, other: AnyExpr) -> FilterExpression:
        raise NotImplementedError

    def __invert__(self) -> FilterExpression:
        raise NotImplementedError


AnyOp = Annotated[
    Union[
        Annotated[And, Tag(And.op)],
        Annotated[Or, Tag(Or.op)],
        Annotated[Nor, Tag(Nor.op)],
        Annotated[Not, Tag(Not.op)],
        # ------------------------------------------------------------------------------
        Annotated[Lt, Tag(Lt.op)],
        Annotated[Gt, Tag(Gt.op)],
        Annotated[Lte, Tag(Lte.op)],
        Annotated[Gte, Tag(Gte.op)],
        Annotated[Eq, Tag(Eq.op)],
        Annotated[Ne, Tag(Ne.op)],
        # ------------------------------------------------------------------------------
        Annotated[In, Tag(In.op)],
        Annotated[NotIn, Tag(NotIn.op)],
        # ------------------------------------------------------------------------------
        Annotated[Regex, Tag(Regex.op)],
        Annotated[Contains, Tag(Contains.op)],
    ],
    Discriminator(get_op_tag),
]

AnyExpr = Union[
    AnyOp,
    FilterExpression,
]
