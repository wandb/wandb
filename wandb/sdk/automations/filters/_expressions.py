"""Pydantic-compatible representations of MongoDB expressions."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Hashable,
    Iterator,
    Mapping,
    Union,
    overload,
)

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Tag,
    model_serializer,
    model_validator,
)
from pydantic.dataclasses import dataclass as pydantic_dataclass
from pydantic_core import to_jsonable_python

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
    RichReprResult,
    Scalar,
    ScalarTypes,
    op_key,
)

if sys.version_info >= (3, 12):
    from typing import Annotated, TypeAlias, dataclass_transform
else:
    from typing_extensions import Annotated, TypeAlias, dataclass_transform

if TYPE_CHECKING:
    from wandb.sdk.automations.events import MetricFilter, RunMetricFilter


@dataclass_transform(eq_default=False, order_default=False, frozen_default=True)
@pydantic_dataclass(eq=False, order=False, frozen=True)
class FilterField:
    """A "filtered" field name or path in a MongoDB query expression."""

    name: str

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name!r})"

    # Methods to define filter expressions through chaining
    def matches_regex(self, pattern: str) -> FilterExpr:
        return FilterExpr(field=self, op=Regex(inner=pattern))

    def contains(self, text: str) -> FilterExpr:
        return FilterExpr(field=self, op=Contains(inner=text))

    def exists(self, exists: bool = True) -> FilterExpr:
        return FilterExpr(field=self, op=Exists(inner=exists))

    def lt(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Lt(inner=value))

    def gt(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Gt(inner=value))

    def lte(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Lte(inner=value))

    def gte(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Gte(inner=value))

    def ne(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Ne(inner=value))

    def eq(self, value: Scalar) -> FilterExpr:
        return FilterExpr(field=self, op=Eq(inner=value))

    def in_(self, values: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr(field=self, op=In(inner=values))

    def not_in(self, values: Iterable[Scalar]) -> FilterExpr:
        return FilterExpr(field=self, op=NotIn(inner=values))

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
    def __eq__(self, other: Any) -> FilterExpr:  # type: ignore[override]
        if isinstance(other, ScalarTypes):
            return self.eq(other)
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")

    def __ne__(self, other: Any) -> FilterExpr:  # type: ignore[override]
        if isinstance(other, ScalarTypes):
            return self.ne(other)
        raise TypeError(f"Invalid operand type in filter expression: {type(other)!r}")


ValidatedFilterField: TypeAlias = Annotated[
    FilterField,
    BeforeValidator(lambda x: FilterField(x) if isinstance(x, str) else x),
]


# ------------------------------------------------------------------------------
class FilterExpr(BaseModel):
    """A MongoDB filter expression on a specific field."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    field: ValidatedFilterField
    op: AnyOpDict

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.field!s}={self.op!r})"

    def __rich_repr__(self) -> RichReprResult:  # type: ignore[override]
        # https://rich.readthedocs.io/en/stable/pretty.html
        yield self.field, self.op

    @overload
    def __and__(self, other: MetricFilter) -> RunMetricFilter: ...
    @overload
    def __and__(self, other: Any) -> And: ...

    def __and__(self, other: Any) -> And | RunMetricFilter:
        from wandb.sdk.automations.events import MetricFilter

        # Special handling for `run_filter & metric_filter`
        if isinstance(other, MetricFilter):
            return other.__and__(self)

        # Default implementation
        return And(inner=[self, other])

    def __or__(self, other: Any) -> Or:
        return Or(inner=[self, other])

    def __invert__(self) -> Not:
        return Not(inner=self)

    @model_validator(mode="before")
    @classmethod
    def _validate(cls, data: Any) -> Any:
        """Parse a MongoDB dict representation of the filter expression."""
        if (
            isinstance(data, Mapping)
            and len(data) == 1
            and not any(filter_mongolike_keys(data))
        ):
            # This is a dict that doesn't look like a MongoDB expression.
            #
            # Example validation input/output:
            # - in:  `{"display_name": {"$contains": "my-run"}}`
            # - out: `FilterExpr(field="display_name", op=Contains(inner="my-run"))`
            field, op = next(iter(data.items()))
            return dict(field=field, op=op)
        return data

    @model_serializer(mode="plain")
    def _serialize(self) -> dict[str, Any]:
        """Return a MongoDB dict representation of the expression."""
        return {
            self.field.name: (
                self.op.model_dump()
                if isinstance(self.op, OpDict)
                else to_jsonable_python(self.op, serialize_as_any=True)
            )
        }


KNOWN_OPS = frozenset({op_key(cls) for cls in OpDict.__subclasses__()})
UNKNOWN = "UNKNOWN"


def get_mongo_op(obj: Any) -> str:
    """Return the MongoDB key, if any, to identify the Op type in a discrimininated union.

    If there is a key that looks like a MongoDB operator but is unrecognized --
    e.g. "$newOp" -- assume it's still valid and hasn't been implemented in the
    SDK yet, and return an unambiguous placeholder value.  The pydantic field
    definition will then be responsible for ensuring that the object is still
    parsed and serialized accurately.
    """
    if isinstance(obj, dict) and (mongolike_keys := set(filter_mongolike_keys(obj))):
        try:
            return one(mongolike_keys & KNOWN_OPS)
        except ValueError:  # Couldn't find exactly one matching, known mongo key
            return UNKNOWN

    if isinstance(obj, OpDict):
        return op_key(type(obj))

    return UNKNOWN


def filter_mongolike_keys(keys: Iterable[Hashable]) -> Iterator[str]:
    """Yields only the keys that look like MongoDB operators."""
    return (k for k in keys if isinstance(k, str) and k.startswith("$"))


AnyOpDict = Annotated[
    Union[
        Annotated[And, Tag("$and")],
        Annotated[Or, Tag("$or")],
        Annotated[Nor, Tag("$nor")],
        Annotated[Not, Tag("$not")],
        # ------------------------------------------------------------------------------
        Annotated[Lt, Tag("$lt")],
        Annotated[Gt, Tag("$gt")],
        Annotated[Lte, Tag("$lte")],
        Annotated[Gte, Tag("$gte")],
        Annotated[Eq, Tag("$eq")],
        Annotated[Ne, Tag("$ne")],
        # ------------------------------------------------------------------------------
        Annotated[In, Tag("$in")],
        Annotated[NotIn, Tag("$nin")],
        # ------------------------------------------------------------------------------
        Annotated[Exists, Tag("$exists")],
        Annotated[Regex, Tag("$regex")],
        Annotated[Contains, Tag("$contains")],
        # ------------------------------------------------------------------------------
        Annotated[Dict[str, Any], Tag(UNKNOWN)],
    ],
    Discriminator(get_mongo_op),
]
