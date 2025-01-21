"""Pydantic-compatible representations of MongoDB expressions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Mapping

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass as pydantic_dataclass
from pydantic_core import to_json, to_jsonable_python
from typing_extensions import dataclass_transform, override

from wandb._pydantic import IS_PYDANTIC_V2, field_validator, model_validator
from wandb._pydantic.base import CompatBaseModel

from .operators import (
    KEY_TO_OP,
    AnyOp,
    BaseOp,
    Contains,
    Eq,
    Exists,
    Gt,
    Gte,
    In,
    Lt,
    Lte,
    Ne,
    NotIn,
    Regex,
    RichReprResult,
    Scalar,
    ScalarTypes,
    SupportsLogicalOpSyntax,
)

if IS_PYDANTIC_V2:
    from pydantic import model_serializer


@dataclass_transform(eq_default=False, order_default=False, frozen_default=True)
@pydantic_dataclass(eq=False, order=False, frozen=True)
class FilterField:
    """A "filtered" field name or path in a MongoDB query expression."""

    name: str

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"

    # Methods to define filter expressions through chaining
    def matches_regex(self, pattern: str) -> FilterExpr:
        return FilterExpr(field=self, op=Regex(regex_=pattern))

    def contains(self, text: str) -> FilterExpr:
        return FilterExpr(field=self, op=Contains(contains_=text))

    def exists(self, exists: bool = True) -> FilterExpr:
        return FilterExpr(field=self, op=Exists(exists_=exists))

    def lt(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Lt(lt_=value))

    def gt(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Gt(gt_=value))

    def lte(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Lte(lte_=value))

    def gte(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Gte(gte_=value))

    def ne(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Ne(ne_=value))

    def eq(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Eq(eq_=value))

    def in_(self, values: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr(field=self, op=In(in_=values))

    def not_in(self, values: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr(field=self, op=NotIn(nin_=values))

    # Override the default behavior of comparison operators: <, >=, ==, etc
    def __lt__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.lt(other)
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    def __gt__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.gt(other)
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    def __le__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.lte(other)
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    def __ge__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.gte(other)
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    # Operator behavior is intentionally overridden to allow defining
    # filter expressions like `field == "value"`.  See similar overrides
    # of built-in dunder methods in sqlalchemy, polars, pandas, numpy, etc.
    #
    # sqlalchemy example for illustrative purposes:
    # https://github.com/sqlalchemy/sqlalchemy/blob/f21ae633486380a26dc0b67b70ae1c0efc6b4dc4/lib/sqlalchemy/orm/descriptor_props.py#L808-L812
    def __eq__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.eq(other)
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    def __ne__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.ne(other)
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")


# ------------------------------------------------------------------------------
class FilterExpr(CompatBaseModel, SupportsLogicalOpSyntax):
    """A MongoDB filter expression on a specific field."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    field: FilterField
    op: AnyOp

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.field!s}={self.op!r})"

    def __rich_repr__(self) -> RichReprResult:  # type: ignore[override]
        # https://rich.readthedocs.io/en/stable/pretty.html
        yield self.field, self.op

    @field_validator("field", mode="before")
    @classmethod
    def _validate_field(cls, v: Any) -> Any:
        return FilterField(v) if isinstance(v, str) else v

    @field_validator("op")
    @classmethod
    def _validate_op(cls, v: Any) -> Any:
        if isinstance(v, BaseOp):
            return v

        if (
            isinstance(v, dict)
            and len(v) == 1
            and (op_key := next(iter(v)))
            and (op_cls := KEY_TO_OP.get(op_key))
        ):
            return op_cls.model_validate(v)
        return v

    @model_validator(mode="before")
    @classmethod
    def _validate(cls, data: Any) -> Any:
        """Parse a MongoDB dict representation of the filter expression."""
        if (
            isinstance(data, Mapping)
            and len(data) == 1
            and not any(k for k in data if isinstance(k, str) and k.startswith("$"))
        ):
            # This is a dict that doesn't look like a MongoDB expression.
            #
            # Example validation input/output:
            # - in:  `{"display_name": {"$contains": "my-run"}}`
            # - out: `FilterExpr(field="display_name", op=Contains(contains_="my-run"))`
            field, op = next(iter(data.items()))
            return dict(field=field, op=op)
        return data

    if IS_PYDANTIC_V2:

        @model_serializer(mode="plain")
        def _serialize(self) -> dict[str, Any]:
            """Return a MongoDB dict representation of the expression."""
            op_dict = to_jsonable_python(self.op, by_alias=True, round_trip=True)
            return {self.field.name: op_dict}
    else:
        # Pydantic V1 workaround -- both model_dump/model_dump_json need to be patched
        @override
        def model_dump(self, **_: Any) -> dict[str, Any]:
            """Return a MongoDB dict representation of the expression."""
            op_dict = self.op.model_dump() if isinstance(self.op, BaseOp) else self.op
            return {self.field.name: op_dict}

        @override
        def model_dump_json(self, **kwargs: Any) -> str:
            """Return a MongoDB JSON string representation of the expression."""
            return to_json(self.model_dump(**kwargs)).decode("utf8")
