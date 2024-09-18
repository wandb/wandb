"""Pydantic-compatible representations of MongoDB expressions (e.g. for queries, filtering, aggregation)."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import chain
from typing import TYPE_CHECKING, Any, Union

from more_itertools import always_iterable
from pydantic import GetCoreSchemaHandler, RootModel
from pydantic._internal import _repr
from pydantic.main import IncEx
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function, str_schema
from typing_extensions import Literal

from wandb.sdk.automations.operators.base import Op
from wandb.sdk.automations.operators.comparison import (
    AnyComparisonOp,
    Eq,
    Gt,
    Gte,
    In,
    Lt,
    Lte,
    Ne,
    Nin,
)
from wandb.sdk.automations.operators.evaluation import AnyEvaluationOp, Regex
from wandb.sdk.automations.operators.logic import And, AnyLogicalOp, Nor, Not, Or

if TYPE_CHECKING:
    from wandb.sdk.automations.operators.comparison import ValueT


# ------------------------------------------------------------------------------
class ExpressionField(str):
    """A field name in a MongoDB query expression that identifies which field the criteria is evaluated on."""

    def __hash__(self) -> int:
        return super().__hash__()

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type[Any], handler: GetCoreSchemaHandler
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
    def lt(self, value: ValueT) -> FieldFilter:
        return self.__lt__(value)

    def gt(self, value: ValueT) -> FieldFilter:
        return self.__gt__(value)

    def lte(self, value: ValueT) -> FieldFilter:
        return self.__le__(value)

    def gte(self, value: ValueT) -> FieldFilter:
        return self.__ge__(value)

    def ne(self, value: ValueT) -> FieldFilter:
        return self.__ne__(value)

    def eq(self, value: ValueT) -> FieldFilter:
        return self.__eq__(value)

    def is_in(self, values: Iterable[ValueT]) -> FieldFilter:
        return FieldFilter.model_validate({self: In(vals=values)})

    def not_in(self, values: Iterable[ValueT]) -> FieldFilter:
        return FieldFilter.model_validate({self: Nin(vals=values)})

    def regex_match(self, pattern: str) -> FieldFilter:
        return FieldFilter.model_validate({self: Regex(regex=pattern)})

    # ------------------------------------------------------------------------------
    def __lt__(self, value: ValueT) -> FieldFilter:
        return FieldFilter.model_validate({self: Lt(val=value)})

    def __gt__(self, value: ValueT) -> FieldFilter:
        return FieldFilter.model_validate({self: Gt(val=value)})

    def __le__(self, value: ValueT) -> FieldFilter:
        return FieldFilter.model_validate({self: Lte(val=value)})

    def __ge__(self, value: ValueT) -> FieldFilter:
        return FieldFilter.model_validate({self: Gte(val=value)})

    def __eq__(self, value: ValueT) -> FieldFilter:
        return FieldFilter.model_validate({self: Eq(val=value)})

    def __ne__(self, value: ValueT) -> FieldFilter:
        return FieldFilter.model_validate({self: Ne(val=value)})


# ------------------------------------------------------------------------------
class FieldFilter(RootModel):
    root: dict[ExpressionField, AnyOp]

    def __repr_args__(self) -> _repr.ReprArgs:
        yield from self.root.items()

    def model_dump(  # type: ignore
        self,
        *,
        mode: Literal["json", "python"] | str = "json",  # NOTE: changed default
        include: IncEx = None,
        exclude: IncEx = None,
        context: dict[str, Any] | None = None,
        by_alias: bool = True,  # NOTE: changed default
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
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

    def model_dump_json(
        self,
        *,
        indent: int | None = None,
        include: IncEx = None,
        exclude: IncEx = None,
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

    def __and__(self, other: AnyExpr) -> FieldFilter:
        raise NotImplementedError

    def __or__(self, other: AnyExpr) -> FieldFilter:
        raise NotImplementedError

    def __invert__(self) -> FieldFilter:
        raise NotImplementedError


AnyOp = Union[
    AnyLogicalOp,
    AnyComparisonOp,
    AnyEvaluationOp,
]
#     # Discriminator(get_op_discriminator_value),
# ]

AnyExpr = Union[
    AnyOp,
    FieldFilter,
]


# ------------------------------------------------------------------------------
# Convenience functions to make constructing/composing operators less verbose and tedious
def or_(*exprs: AnyExpr | Iterable[AnyExpr]) -> Or:
    all_exprs = chain.from_iterable(always_iterable(x, base_type=Op) for x in exprs)
    return Or(exprs=all_exprs)


def and_(*exprs: AnyExpr | Iterable[AnyExpr]) -> And:
    all_exprs = chain.from_iterable(always_iterable(x, base_type=Op) for x in exprs)
    return And(exprs=all_exprs)


def none_of(*exprs: AnyExpr | Iterable[AnyExpr]) -> Nor:
    all_exprs = chain.from_iterable(always_iterable(x, base_type=Op) for x in exprs)
    return Nor(exprs=all_exprs)


def not_(expr: AnyExpr) -> Not:
    return Not(expr=expr)


def gt(val: ValueT) -> Gt:
    return Gt(val=val)


def gte(val: ValueT) -> Gte:
    return Gte(val=val)


def lt(val: ValueT) -> Lt:
    return Lt(val=val)


def lte(val: ValueT) -> Lte:
    return Lte(val=val)


def eq(val: ValueT) -> Eq:
    return Eq(val=val)


def ne(val: ValueT) -> Ne:
    return Ne(val=val)


# ------------------------------------------------------------------------------
def regex(pattern: str) -> Regex:
    return Regex(regex=pattern)


# ------------------------------------------------------------------------------
def on_field(field: str) -> ExpressionField:
    # When/if needed for greater flexiblity:
    # handle when class attributes e.g. `Artifact.tags/aliases` are passed directly as well
    return ExpressionField(field)
