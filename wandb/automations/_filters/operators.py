"""Types that represent operators in MongoDB filter expressions."""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, Iterable, Tuple, TypeVar, Union

from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from typing_extensions import Self, TypeAlias, get_args, override

from wandb._pydantic import GQLBase
from wandb._strutils import nameof

if TYPE_CHECKING:
    from .expressions import FilterExpr

# for type annotations
Scalar = Union[StrictStr, StrictInt, StrictFloat, StrictBool]
# for runtime type checks
ScalarTypes: tuple[type, ...] = tuple(t.__origin__ for t in get_args(Scalar))

# See: https://rich.readthedocs.io/en/stable/pretty.html#rich-repr-protocol
RichReprResult: TypeAlias = Iterable[
    Union[
        Any,
        Tuple[Any],
        Tuple[str, Any],
        Tuple[str, Any, Any],
    ]
]

T = TypeVar("T")
TupleOf: TypeAlias = Tuple[T, ...]


# NOTE: Wherever class descriptions that are not docstrings, this is deliberate.
# This is done to ensure the descriptions are omitted from generated API docs.


# Mixin class to support building MongoDB expressions idiomatically
# with bitwise logical operators, e.g.:
#   `a | b` -> `{"$or": [a, b]}`
#   `~a` -> `{"$not": a}`
class SupportsBitwiseLogicalOps:
    def __or__(self, other: Any) -> Or:
        """Implements default `|` behavior: `a | b -> Or(a, b)`."""
        return Or(exprs=(self, other))

    def __and__(self, other: Any) -> And:
        """Implements default `&` behavior: `a & b -> And(a, b)`."""
        from .expressions import FilterExpr

        if isinstance(other, (BaseOp, FilterExpr)):
            return And(exprs=(self, other))
        return NotImplemented

    def __invert__(self) -> Not:
        """Implements default `~` behavior: `~a -> Not(a)`."""
        return Not(expr=self)


# Base type for parsing MongoDB filter operators, e.g. from dicts like
# `{"$and": [...]}`, `{"$or": [...]}`, `{"$gt": 1.0}`, etc.
# Instances are frozen for easier comparison and more predictable behavior.
class BaseOp(GQLBase, SupportsBitwiseLogicalOps, ABC):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    def __repr__(self) -> str:
        """Returns the operator's repr string, with operand(s) as positional args.

        Note that BaseModels implement `__iter__()`:
          https://docs.pydantic.dev/latest/concepts/serialization/#iterating-over-models
        """
        return f"{nameof(type(self))}({', '.join(repr(v) for _, v in self)})"

    def __rich_repr__(self) -> RichReprResult:
        """Returns the operator's rich repr, if pretty-printing via `rich`.

        See: https://rich.readthedocs.io/en/stable/pretty.html
        """
        # Display field values as positional args:
        yield from ((None, v) for _, v in self)


# Base type for logical operators that take a variable number of expressions.
class BaseVariadicLogicalOp(BaseOp, ABC):
    exprs: TupleOf[Union[FilterExpr, Op]]

    @classmethod
    def wrap(cls, expr: Any) -> Self:
        return expr if isinstance(expr, cls) else cls(exprs=(expr,))


# Logical operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/and/
# https://www.mongodb.com/docs/manual/reference/operator/query/or/
# https://www.mongodb.com/docs/manual/reference/operator/query/nor/
# https://www.mongodb.com/docs/manual/reference/operator/query/not/
class And(BaseVariadicLogicalOp):
    exprs: TupleOf[Union[FilterExpr, Op]] = Field(default=(), alias="$and")


class Or(BaseVariadicLogicalOp):
    exprs: TupleOf[Union[FilterExpr, Op]] = Field(default=(), alias="$or")

    @override
    def __invert__(self) -> Nor:
        """Implements `~Or(a, b) -> Nor(a, b)`."""
        return Nor(exprs=self.exprs)


class Nor(BaseVariadicLogicalOp):
    exprs: TupleOf[Union[FilterExpr, Op]] = Field(default=(), alias="$nor")

    @override
    def __invert__(self) -> Or:
        """Implements `~Nor(a, b) -> Or(a, b)`."""
        return Or(exprs=self.exprs)


class Not(BaseOp):
    expr: Union[FilterExpr, Op] = Field(alias="$not")

    @override
    def __invert__(self) -> Union[FilterExpr, Op]:
        """Implements `~Not(a) -> a`."""
        return self.expr


# Comparison operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/lt/
# https://www.mongodb.com/docs/manual/reference/operator/query/gt/
# https://www.mongodb.com/docs/manual/reference/operator/query/lte/
# https://www.mongodb.com/docs/manual/reference/operator/query/gte/
# https://www.mongodb.com/docs/manual/reference/operator/query/eq/
# https://www.mongodb.com/docs/manual/reference/operator/query/ne/
# https://www.mongodb.com/docs/manual/reference/operator/query/in/
# https://www.mongodb.com/docs/manual/reference/operator/query/nin/
class Lt(BaseOp):
    val: Scalar = Field(alias="$lt")

    @override
    def __invert__(self) -> Gte:
        """Implements `~Lt(a) -> Gte(a)`."""
        return Gte(val=self.val)


class Gt(BaseOp):
    val: Scalar = Field(alias="$gt")

    @override
    def __invert__(self) -> Lte:
        """Implements `~Gt(a) -> Lte(a)`."""
        return Lte(val=self.val)


class Lte(BaseOp):
    val: Scalar = Field(alias="$lte")

    @override
    def __invert__(self) -> Gt:
        """Implements `~Lte(a) -> Gt(a)`."""
        return Gt(val=self.val)


class Gte(BaseOp):
    val: Scalar = Field(alias="$gte")

    @override
    def __invert__(self) -> Lt:
        """Implements `~Gte(a) -> Lt(a)`."""
        return Lt(val=self.val)


class Eq(BaseOp):
    val: Scalar = Field(alias="$eq")

    @override
    def __invert__(self) -> Ne:
        """Implements `~Eq(a) -> Ne(a)`."""
        return Ne(val=self.val)


class Ne(BaseOp):
    val: Scalar = Field(alias="$ne")

    @override
    def __invert__(self) -> Eq:
        """Implements `~Ne(a) -> Eq(a)`."""
        return Eq(val=self.val)


class In(BaseOp):
    val: TupleOf[Scalar] = Field(default=(), alias="$in")

    @override
    def __invert__(self) -> NotIn:
        """Implements `~In(a) -> NotIn(a)`."""
        return NotIn(val=self.val)


class NotIn(BaseOp):
    val: TupleOf[Scalar] = Field(default=(), alias="$nin")

    @override
    def __invert__(self) -> In:
        """Implements `~NotIn(a) -> In(a)`."""
        return In(val=self.val)


# Element operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/exists/
class Exists(BaseOp):
    val: bool = Field(alias="$exists")

    @override
    def __invert__(self) -> Exists:
        """Implements `~Exists(True) -> Exists(False)` and vice versa."""
        return Exists(val=not self.val)


# Evaluation operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/regex/
#
# Note: `$contains` is NOT a formal MongoDB operator, but the W&B backend
# recognizes and executes it as a substring-match filter.
class Regex(BaseOp):
    val: str = Field(alias="$regex")  #: The regex expression to match against.


class Contains(BaseOp):
    val: str = Field(alias="$contains")  #: The substring to match against.


# ------------------------------------------------------------------------------
# Convenience helpers, constants, and utils for supported MongoDB operators
# ------------------------------------------------------------------------------
KEY_TO_OP: dict[str, type[BaseOp]] = {
    "$and": And,
    "$or": Or,
    "$nor": Nor,
    "$not": Not,
    "$lt": Lt,
    "$gt": Gt,
    "$lte": Lte,
    "$gte": Gte,
    "$eq": Eq,
    "$ne": Ne,
    "$in": In,
    "$nin": NotIn,
    "$exists": Exists,
    "$regex": Regex,
    "$contains": Contains,
}


# Known, implemented MongoDB operators for type annotations.
Op = Union[
    And,
    Or,
    Nor,
    Not,
    Lt,
    Gt,
    Lte,
    Gte,
    Eq,
    Ne,
    In,
    NotIn,
    Exists,
    Regex,
    Contains,
]
