"""Pydantic-compatible representations of MongoDB expressions (e.g. for queries, filtering, aggregation)."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import Any, Dict, Iterator, Mapping, Union

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

from wandb._iterutils import one

from ._operators import (
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

    def exists(self, exists: bool = True) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$exists": exists}})

    def lt(self, value: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$lt": value}})

    def gt(self, value: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$gt": value}})

    def lte(self, value: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$lte": value}})

    def gte(self, value: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$gte": value}})

    def ne(self, value: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$ne": value}})

    def eq(self, value: Scalar) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$eq": value}})

    def in_(self, values: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$in": values}})

    def not_in(self, values: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr.model_validate({self: {"$not_in": values}})

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
    op: AnyOpDict

    def __repr_args__(self) -> _repr.ReprArgs:
        yield self.field, self.op

    def __and__(self, other: Any) -> And:
        return And(inner=[self, other])

    def __or__(self, other: Any) -> Or:
        return Or(inner=[self, other])

    def __invert__(self) -> Not:
        return Not(inner=self)

    @model_validator(mode="before")
    @classmethod
    def _validate(cls, data: Any) -> Any:
        """Parse from a MongoDB dict representation of the expression, e.g. `{"display_name": {"$contains": "my-run"}}`."""
        if (
            isinstance(data, Mapping)
            and len(data) == 1
            and not has_mongolike_keys(data)
        ):
            field, op = next(iter(data.items()))
            return dict(field=field, op=op)
        return data

    @model_serializer(mode="plain")
    def _serialize(self) -> dict[str, Any]:
        """Return a MongoDB dict representation of the expression."""
        return {
            to_jsonable_python(self.field): to_jsonable_python(
                self.op, serialize_as_any=True
            )
        }


_KNOWN_OPS = frozenset({cls.OP for cls in OpDict.__subclasses__()})
_UNKNOWN = "UNKNOWN"


def get_mongolike_key(obj: Any) -> Any:
    """Return the mongo-like op key to identify the Op type in a union, or "UNKNOWN" if not found."""
    if isinstance(obj, dict):
        try:
            op = one(filter_mongolike_keys(obj))
        except ValueError:  # Couldn't find exactly one matching mongo key
            return _UNKNOWN
        else:
            return op if (op in _KNOWN_OPS) else _UNKNOWN

    if isinstance(obj, OpDict):
        return obj.OP

    return _UNKNOWN


def filter_mongolike_keys(keys: Iterable[str]) -> Iterator[str]:
    """Yields only the keys that look like MongoDB operators."""
    return (k for k in keys if k.startswith("$"))


def has_mongolike_keys(keys: Iterable[str]) -> bool:
    """Returns True if the data has any keys that look like MongoDB operators."""
    return any(filter_mongolike_keys(keys))


AnyOpDict = Annotated[
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
        Annotated[Exists, Tag(Exists.OP)],
        Annotated[Regex, Tag(Regex.OP)],
        Annotated[Contains, Tag(Contains.OP)],
        # ------------------------------------------------------------------------------
        Annotated[Dict[str, Any], Tag(_UNKNOWN)],
    ],
    Discriminator(get_mongolike_key),
]
