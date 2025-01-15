"""Pydantic-compatible representations of MongoDB expressions (e.g. for queries, filtering, aggregation)."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import Any, Iterator, Union

from pydantic import (
    BaseModel,
    Discriminator,
    GetCoreSchemaHandler,
    Tag,
    model_serializer,
    model_validator,
)
from pydantic._internal import _repr
from pydantic_core import CoreSchema, to_jsonable_python
from pydantic_core.core_schema import no_info_after_validator_function

from ._operators import (
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
    OpDict,
    Or,
    Regex,
    Scalar,
)

if sys.version_info >= (3, 12):
    from typing import Annotated
else:
    from typing_extensions import Annotated


# ------------------------------------------------------------------------------
class FilterField(str):
    """A name or path that identifies a "filtered" field in a MongoDB query expression."""

    # Prevents error on validation: `TypeError: unhashable type: 'FilterField'`
    __hash__ = str.__hash__

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        # See: https://docs.pydantic.dev/latest/concepts/json_schema/#skipjsonschema-annotation
        return no_info_after_validator_function(cls, handler(str))

    # Methods to define filter expressions through chaining
    def matches_regex(self, pattern: str) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$regex": pattern}})

    def contains(self, text: str) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$contains": text}})

    def lt(self, other: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$lt": other}})

    def gt(self, other: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$gt": other}})

    def lte(self, other: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$lte": other}})

    def gte(self, other: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$gte": other}})

    def ne(self, other: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$ne": other}})

    def eq(self, other: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$eq": other}})

    def in_(self, other: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$in": other}})

    def not_in(self, other: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$not_in": other}})

    __lt__ = lt  # type: ignore[assignment]
    __gt__ = gt  # type: ignore[assignment]
    __le__ = lte  # type: ignore[assignment]
    __ge__ = gte  # type: ignore[assignment]
    __eq__ = eq  # type: ignore[assignment]
    __ne__ = ne  # type: ignore[assignment]


# ------------------------------------------------------------------------------
class FilterExpr(BaseModel):
    """A MongoDB filter expression for a specific field."""

    field: FilterField
    op: AnyOp

    def __repr_args__(self) -> _repr.ReprArgs:
        yield self.field, self.op

    def __and__(self, other: Any) -> And:
        return And(other=[self, other])

    def __or__(self, other: Any) -> Or:
        return Or(other=[self, other])

    def __invert__(self) -> Not:
        return Not(other=self)

    @model_validator(mode="before")
    @classmethod
    def from_dict(cls, data: Any) -> Any:
        """Parse from a MongoDB dict representation of the expression, e.g. `{"display_name": {"$contains": "my-run"}}`."""
        if (
            isinstance(data, dict)
            and len(data) == 1
            and not any(filter_mongo_keys(data))
        ):
            field, op = next(iter(data.items()))
            return dict(field=field, op=op)
        return data

    @model_serializer(mode="plain")
    def to_dict(self) -> dict[str, Any]:
        """Return a MongoDB dict representation of the expression."""
        return {to_jsonable_python(self.field): self.op.model_dump()}


def get_mongo_op(obj: Any) -> Any:
    """Return the discriminator tag to identify the Op type in a tagged union."""
    if isinstance(obj, dict):
        try:
            [op_key] = filter_mongo_keys(obj)
        except ValueError:
            return None
        else:
            return op_key
    if isinstance(obj, OpDict):
        return obj.OP
    return None


def filter_mongo_keys(keys: Iterable[str]) -> Iterator[str]:
    """Yields only the keys that look like MongoDB operators."""
    return (k for k in keys if k.startswith("$"))


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
    Discriminator(get_mongo_op),
]
