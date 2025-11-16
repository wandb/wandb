"""Types that represent operators in MongoDB filter expressions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Tuple, TypeVar, Union

from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from typing_extensions import TypeAlias, get_args, override

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


# Mixin to support syntactic sugar for MongoDB expressions with bitwise
# logical operators, e.g.:
#   `a | b` -> `{"$or": [a, b]}`
#   `~a` -> `{"$not": a}`
class SupportsLogicalOpSyntax:
    def __or__(self, other: Any) -> Or:
        """Implements default behavior: `a | b -> Or(a, b)`."""
        return Or(or_=[self, other])

    def __and__(self, other: Any) -> And:
        """Implements default behavior: `a & b -> And(a, b)`."""
        from .expressions import FilterExpr

        if isinstance(other, (BaseOp, FilterExpr)):
            return And(and_=[self, other])
        return NotImplemented

    def __invert__(self) -> Not:
        """Implements default behavior: `~a -> Not(a)`."""
        return Not(not_=self)


# Base type for parsing MongoDB filter operators, e.g. from dicts like
# `{"$and": [...]}`, `{"$or": [...]}`, `{"$gt": 1.0}`, etc.
# Instances are frozen for easier comparison and more predictable behavior.
class BaseOp(GQLBase, SupportsLogicalOpSyntax):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    def __repr__(self) -> str:
        # Display the operand(s) as positional args
        # Note that BaseModels implement `__iter__`:
        #   https://docs.pydantic.dev/latest/concepts/serialization/#iterating-over-models
        values_repr = ", ".join(repr(v) for _, v in self)
        return f"{nameof(type(self))}({values_repr})"

    def __rich_repr__(self) -> RichReprResult:
        # Display field values as positional args:
        # https://rich.readthedocs.io/en/stable/pretty.html
        yield from ((None, v) for _, v in self)


# Logical operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/and/
# https://www.mongodb.com/docs/manual/reference/operator/query/or/
# https://www.mongodb.com/docs/manual/reference/operator/query/nor/
# https://www.mongodb.com/docs/manual/reference/operator/query/not/
class And(BaseOp):
    and_: TupleOf[Union[FilterExpr, Op]] = Field(default=(), alias="$and")


class Or(BaseOp):
    or_: TupleOf[Union[FilterExpr, Op]] = Field(default=(), alias="$or")

    @override
    def __invert__(self) -> Nor:
        """Implements `~Or(a, b) -> Nor(a, b)`."""
        return Nor(nor_=self.or_)


class Nor(BaseOp):
    nor_: TupleOf[Union[FilterExpr, Op]] = Field(default=(), alias="$nor")

    @override
    def __invert__(self) -> Or:
        """Implements `~Nor(a, b) -> Or(a, b)`."""
        return Or(or_=self.nor_)


class Not(BaseOp):
    not_: Union[FilterExpr, Op] = Field(alias="$not")

    @override
    def __invert__(self) -> Union[FilterExpr, Op]:
        """Implements `~Not(a) -> a`."""
        return self.not_


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
    lt_: Scalar = Field(alias="$lt")

    @override
    def __invert__(self) -> Gte:
        """Implements `~Lt(a) -> Gte(a)`."""
        return Gte(gte_=self.lt_)


class Gt(BaseOp):
    gt_: Scalar = Field(alias="$gt")

    @override
    def __invert__(self) -> Lte:
        """Implements `~Gt(a) -> Lte(a)`."""
        return Lte(lte_=self.gt_)


class Lte(BaseOp):
    lte_: Scalar = Field(alias="$lte")

    @override
    def __invert__(self) -> Gt:
        """Implements `~Lte(a) -> Gt(a)`."""
        return Gt(gt_=self.lte_)


class Gte(BaseOp):
    gte_: Scalar = Field(alias="$gte")

    @override
    def __invert__(self) -> Lt:
        """Implements `~Gte(a) -> Lt(a)`."""
        return Lt(lt_=self.gte_)


class Eq(BaseOp):
    eq_: Scalar = Field(alias="$eq")

    @override
    def __invert__(self) -> Ne:
        """Implements `~Eq(a) -> Ne(a)`."""
        return Ne(ne_=self.eq_)


class Ne(BaseOp):
    ne_: Scalar = Field(alias="$ne")

    @override
    def __invert__(self) -> Eq:
        """Implements `~Ne(a) -> Eq(a)`."""
        return Eq(eq_=self.ne_)


class In(BaseOp):
    in_: TupleOf[Scalar] = Field(default=(), alias="$in")

    @override
    def __invert__(self) -> NotIn:
        """Implements `~In(a) -> NotIn(a)`."""
        return NotIn(nin_=self.in_)


class NotIn(BaseOp):
    nin_: TupleOf[Scalar] = Field(default=(), alias="$nin")

    @override
    def __invert__(self) -> In:
        """Implements `~NotIn(a) -> In(a)`."""
        return In(in_=self.nin_)


# Element operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/exists/
class Exists(BaseOp):
    exists_: bool = Field(alias="$exists")

    @override
    def __invert__(self) -> Exists:
        """Implements `~Exists(True) -> Exists(False)` and vice versa."""
        return Exists(exists_=not self.exists_)


# Evaluation operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/regex/
#
# Note: `$contains` is NOT a formal MongoDB operator, but the W&B backend
# recognizes and executes it as a substring-match filter.
class Regex(BaseOp):
    regex_: str = Field(alias="$regex")  #: The regex expression to match against.


class Contains(BaseOp):
    contains_: str = Field(alias="$contains")  #: The substring to match against.


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


# for type annotations
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
