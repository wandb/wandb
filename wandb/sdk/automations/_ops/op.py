"""Pydantic-compatible representations of MongoDB expressions (e.g. for queries, filtering, aggregation)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Union

from pydantic import GetCoreSchemaHandler, RootModel
from pydantic._internal import _repr
from pydantic.main import IncEx
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function, str_schema
from typing_extensions import Literal

try:
    from typing_extensions import override
except ImportError:
    from typing import override

from wandb.sdk.automations._ops.comparison import (
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
from wandb.sdk.automations._ops.evaluation import AnyEvaluationOp, Regex
from wandb.sdk.automations._ops.logic import AnyLogicalOp

if TYPE_CHECKING:
    from wandb.sdk.automations._ops.comparison import ValueT


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
    def __lt__(self, value: ValueT) -> FieldFilter:  # type: ignore[override,misc]
        return FieldFilter.model_validate({self: Lt(val=value)})

    def __gt__(self, value: ValueT) -> FieldFilter:  # type: ignore[override,misc]
        return FieldFilter.model_validate({self: Gt(val=value)})

    def __le__(self, value: ValueT) -> FieldFilter:  # type: ignore[override,misc]
        return FieldFilter.model_validate({self: Lte(val=value)})

    def __ge__(self, value: ValueT) -> FieldFilter:  # type: ignore[override,misc]
        return FieldFilter.model_validate({self: Gte(val=value)})

    def __eq__(self, value: ValueT) -> FieldFilter:  # type: ignore[override]
        return FieldFilter.model_validate({self: Eq(val=value)})

    def __ne__(self, value: ValueT) -> FieldFilter:  # type: ignore[override]
        return FieldFilter.model_validate({self: Ne(val=value)})


# ------------------------------------------------------------------------------
class FieldFilter(RootModel):
    root: dict[ExpressionField, AnyOp]

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

AnyExpr = Union[
    AnyOp,
    FieldFilter,
]
