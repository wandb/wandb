"""Pydantic-compatible representations of MongoDB expressions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Union

from pydantic import ConfigDict, model_serializer
from typing_extensions import Self, TypeAlias, get_args

from wandb._pydantic import CompatBaseModel, model_validator
from wandb._strutils import nameof

from .operators import (
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
    Op,
    Regex,
    RichReprResult,
    Scalar,
    ScalarTypes,
    SupportsLogicalOpSyntax,
)


class FilterableField:
    """A descriptor that can be used to define a "filterable" field on a class.

    Internal helper to support syntactic sugar for defining event filters.
    """

    _python_name: str  #: The name of the field this descriptor was assigned to in the Python class.
    _server_name: str | None  #: If set, the actual server-side field name to filter on.

    def __init__(self, server_name: str | None = None):
        self._server_name = server_name

    def __set_name__(self, owner: type, name: str) -> None:
        self._python_name = name

    def __get__(self, obj: Any, objtype: type) -> Self:
        # By default, if we didn't explicitly provide a backend name for
        # filtering, assume the field has the same name in the backend as
        # the python attribute.
        return self

    @property
    def _name(self) -> str:
        return self._server_name or self._python_name

    def __str__(self) -> str:
        return self._name

    def __repr__(self) -> str:
        return f"{nameof(type(self))}({self._name!r})"

    # Methods to define filter expressions through chaining
    def matches_regex(self, pattern: str) -> FilterExpr:
        return FilterExpr(field=self._name, op=Regex(regex_=pattern))

    def contains(self, text: str) -> FilterExpr:
        return FilterExpr(field=self._name, op=Contains(contains_=text))

    def exists(self, exists: bool = True) -> FilterExpr:
        return FilterExpr(field=self._name, op=Exists(exists_=exists))

    def lt(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self._name, op=Lt(lt_=value))

    def gt(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self._name, op=Gt(gt_=value))

    def lte(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self._name, op=Lte(lte_=value))

    def gte(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self._name, op=Gte(gte_=value))

    def ne(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self._name, op=Ne(ne_=value))

    def eq(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self._name, op=Eq(eq_=value))

    def in_(self, values: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr(field=self._name, op=In(in_=values))

    def not_in(self, values: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr(field=self._name, op=NotIn(nin_=values))

    # Override the default behavior of comparison operators: <, >=, ==, etc
    def __lt__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.lt(other)  # type: ignore[arg-type]
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    def __gt__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.gt(other)  # type: ignore[arg-type]
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    def __le__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.lte(other)  # type: ignore[arg-type]
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    def __ge__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.gte(other)  # type: ignore[arg-type]
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    # Operator behavior is intentionally overridden to allow defining
    # filter expressions like `field == "value"`.  See similar overrides
    # of built-in dunder methods in sqlalchemy, polars, pandas, numpy, etc.
    #
    # sqlalchemy example for illustrative purposes:
    # https://github.com/sqlalchemy/sqlalchemy/blob/f21ae633486380a26dc0b67b70ae1c0efc6b4dc4/lib/sqlalchemy/orm/descriptor_props.py#L808-L812
    def __eq__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.eq(other)  # type: ignore[arg-type]
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    def __ne__(self, other: Any) -> FilterExpr:
        if isinstance(other, ScalarTypes):
            return self.ne(other)  # type: ignore[arg-type]
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")


# ------------------------------------------------------------------------------
class FilterExpr(CompatBaseModel, SupportsLogicalOpSyntax):
    """A MongoDB filter expression on a specific field."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    field: str
    op: Op

    def __repr__(self) -> str:
        return f"{nameof(type(self))}({self.field!s}: {self.op!r})"

    def __rich_repr__(self) -> RichReprResult:
        # https://rich.readthedocs.io/en/stable/pretty.html
        yield self.field, self.op

    @model_validator(mode="before")
    @classmethod
    def _validate(cls, data: Any) -> Any:
        """Parse a MongoDB dict representation of the filter expression."""
        if (
            isinstance(data, dict)
            and len(data) == 1
            and not any(key.startswith("$") for key in data)
        ):
            # This looks like a MongoDB filter dict.  E.g.:
            # - in:  `{"display_name": {"$contains": "my-run"}}`
            # - out: `FilterExpr(field="display_name", op=Contains(contains_="my-run"))`
            ((field, op),) = data.items()
            return {"field": field, "op": op}
        return data

    @model_serializer(mode="plain")
    def _serialize(self) -> dict[str, Any]:
        """Return a MongoDB dict representation of the expression."""
        from pydantic_core import to_jsonable_python  # Only valid in pydantic v2

        return {self.field: to_jsonable_python(self.op, by_alias=True, round_trip=True)}


# for type annotations
MongoLikeFilter: TypeAlias = Union[Op, FilterExpr]
# for runtime type checks
MongoLikeFilterTypes: tuple[type, ...] = get_args(MongoLikeFilter)
