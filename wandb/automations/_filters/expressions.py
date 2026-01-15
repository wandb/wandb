"""Pydantic-compatible representations of MongoDB expressions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Union

from pydantic import BaseModel, ConfigDict, model_serializer, model_validator
from typing_extensions import Self, TypeAlias

from wandb._strutils import nameof

from .operators import (
    And,
    Contains,
    Eq,
    Exists,
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
    RichReprResult,
    Scalar,
    SupportsBitwiseLogicalOps,
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
    def matches_regex(self, pattern: str, /) -> FilterExpr:
        return FilterExpr(field=self._name, op=Regex(val=pattern))

    def contains(self, text: str, /) -> FilterExpr:
        return FilterExpr(field=self._name, op=Contains(val=text))

    def exists(self, exists: bool = True, /) -> FilterExpr:
        return FilterExpr(field=self._name, op=Exists(val=exists))

    def lt(self, value: Scalar, /) -> FilterExpr:
        return FilterExpr(field=self._name, op=Lt(val=value))

    def gt(self, value: Scalar, /) -> FilterExpr:
        return FilterExpr(field=self._name, op=Gt(val=value))

    def lte(self, value: Scalar, /) -> FilterExpr:
        return FilterExpr(field=self._name, op=Lte(val=value))

    def gte(self, value: Scalar, /) -> FilterExpr:
        return FilterExpr(field=self._name, op=Gte(val=value))

    def ne(self, value: Scalar, /) -> FilterExpr:
        return FilterExpr(field=self._name, op=Ne(val=value))

    def eq(self, value: Scalar, /) -> FilterExpr:
        return FilterExpr(field=self._name, op=Eq(val=value))

    def in_(self, values: Iterable[Scalar], /) -> FilterExpr:
        return FilterExpr(field=self._name, op=In(val=values))

    def not_in(self, values: Iterable[Scalar], /) -> FilterExpr:
        return FilterExpr(field=self._name, op=NotIn(val=values))

    # Deliberately override the default behavior of comparison operator symbols,
    # (`<`, `>`, `<=`, `>=`, `==`, `!=`), to allow defining filter expressions
    # idiomatically, e.g. `field == "value"`.
    #
    # See similar overrides of built-in dunder methods in common libraries like
    # `sqlalchemy`, `polars`, `pandas`, `numpy`, etc.
    #
    # As an illustrative example from `sqlalchemy`, see:
    # https://github.com/sqlalchemy/sqlalchemy/blob/f21ae633486380a26dc0b67b70ae1c0efc6b4dc4/lib/sqlalchemy/orm/descriptor_props.py#L808-L812
    def __lt__(self, other: Any) -> FilterExpr:
        return self.lt(other)

    def __gt__(self, other: Any) -> FilterExpr:
        return self.gt(other)

    def __le__(self, other: Any) -> FilterExpr:
        return self.lte(other)

    def __ge__(self, other: Any) -> FilterExpr:
        return self.gte(other)

    def __eq__(self, other: Any) -> FilterExpr:  # type: ignore[override]
        return self.eq(other)

    def __ne__(self, other: Any) -> FilterExpr:  # type: ignore[override]
        return self.ne(other)


# ------------------------------------------------------------------------------
class FilterExpr(BaseModel, SupportsBitwiseLogicalOps):
    """A MongoDB filter expression on a specific field."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    field: str
    op: Op | dict[str, Any]

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
            # This looks like a MongoDB filter expression on a single field.  E.g.:
            # - in:  `{"display_name": {"$contains": "my-run"}}`
            # - out: `FilterExpr(field="display_name", op=Contains(val="my-run"))`
            ((field, op),) = data.items()
            return {"field": field, "op": op}
        return data

    @model_serializer(mode="plain")
    def _to_mongo_dict(self) -> dict[str, Any]:
        """Return a MongoDB dict representation of the expression."""
        from pydantic_core import to_jsonable_python  # Only valid in pydantic v2

        return {self.field: to_jsonable_python(self.op, by_alias=True, round_trip=True)}


# Some of the MongoDB op types need to be rebuilt after defining FilterExpr,
# due to forward references.
And.model_rebuild()
Or.model_rebuild()
Nor.model_rebuild()
Not.model_rebuild()

# for type annotations
MongoLikeFilter: TypeAlias = Union[Op, FilterExpr, dict[str, Any]]
