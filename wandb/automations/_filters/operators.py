"""Types that represent operators in MongoDB filter expressions."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple, TypeVar, Union

from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from typing_extensions import TypeAlias, get_args

from wandb._pydantic import GQLBase
from wandb._strutils import nameof

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


# Mixin to support syntactic sugar for MongoDB expressions with (bitwise) logical operators,
# e.g. `a | b` -> `{"$or": [a, b]}` or `~a` -> `{"$not": a}`.
class SupportsLogicalOpSyntax:
    def __or__(self, other: Any) -> Or:
        """Syntactic sugar for: `a | b` -> `Or(a, b)`."""
        return Or(or_=[self, other])

    def __and__(self, other: Any) -> And:
        """Syntactic sugar for: `a & b` -> `And(a, b)`."""
        from .expressions import FilterExpr

        if isinstance(other, (BaseOp, FilterExpr)):
            return And(and_=[self, other])
        return NotImplemented

    def __invert__(self) -> Not:
        """Syntactic sugar for: `~a` -> `Not(a)`."""
        return Not(not_=self)


# Base class for parsed MongoDB filter/query operators, e.g. `{"$and": [...]}`.
class BaseOp(GQLBase, SupportsLogicalOpSyntax):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,  # Make pseudo-immutable for easier comparison and hashing
    )

    def __repr__(self) -> str:
        # Display operand as a positional arg
        values_repr = ", ".join(map(repr, self.model_dump().values()))
        return f"{nameof(type(self))}({values_repr})"

    def __rich_repr__(self) -> RichReprResult:
        # Display field values as positional args:
        # https://rich.readthedocs.io/en/stable/pretty.html
        yield from ((None, v) for v in self.model_dump().values())


# Logical operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/and/
# https://www.mongodb.com/docs/manual/reference/operator/query/or/
# https://www.mongodb.com/docs/manual/reference/operator/query/nor/
# https://www.mongodb.com/docs/manual/reference/operator/query/not/
class And(BaseOp):
    and_: TupleOf[Any] = Field(default=(), alias="$and")


class Or(BaseOp):
    or_: TupleOf[Any] = Field(default=(), alias="$or")

    def __invert__(self) -> Nor:
        """Syntactic sugar for: `~Or(a, b)` -> `Nor(a, b)`."""
        return Nor(nor_=self.or_)


class Nor(BaseOp):
    nor_: TupleOf[Any] = Field(default=(), alias="$nor")

    def __invert__(self) -> Or:
        """Syntactic sugar for: `~Nor(a, b)` -> `Or(a, b)`."""
        return Or(or_=self.nor_)


class Not(BaseOp):
    not_: Any = Field(alias="$not")

    def __invert__(self) -> Any:
        """Syntactic sugar for: `~Not(a)` -> `a`."""
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

    def __invert__(self) -> Gte:
        """Syntactic sugar for: `~Lt(a)` -> `Gte(a)`."""
        return Gte(gte_=self.lt_)


class Gt(BaseOp):
    gt_: Scalar = Field(alias="$gt")

    def __invert__(self) -> Lte:
        """Syntactic sugar for: `~Gt(a)` -> `Lte(a)`."""
        return Lte(lte_=self.gt_)


class Lte(BaseOp):
    lte_: Scalar = Field(alias="$lte")

    def __invert__(self) -> Gt:
        """Syntactic sugar for: `~Lte(a)` -> `Gt(a)`."""
        return Gt(gt_=self.lte_)


class Gte(BaseOp):
    gte_: Scalar = Field(alias="$gte")

    def __invert__(self) -> Lt:
        """Syntactic sugar for: `~Gte(a)` -> `Lt(a)`."""
        return Lt(lt_=self.gte_)


class Eq(BaseOp):
    eq_: Scalar = Field(alias="$eq")

    def __invert__(self) -> Ne:
        """Syntactic sugar for: `~Eq(a)` -> `Ne(a)`."""
        return Ne(ne_=self.eq_)


class Ne(BaseOp):
    ne_: Scalar = Field(alias="$ne")

    def __invert__(self) -> Eq:
        """Syntactic sugar for: `~Ne(a)` -> `Eq(a)`."""
        return Eq(eq_=self.ne_)


class In(BaseOp):
    in_: TupleOf[Scalar] = Field(default=(), alias="$in")

    def __invert__(self) -> NotIn:
        """Syntactic sugar for: `~In(a)` -> `NotIn(a)`."""
        return NotIn(nin_=self.in_)


class NotIn(BaseOp):
    nin_: TupleOf[Scalar] = Field(default=(), alias="$nin")

    def __invert__(self) -> In:
        """Syntactic sugar for: `~NotIn(a)` -> `In(a)`."""
        return In(in_=self.nin_)


# Element operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/exists/
class Exists(BaseOp):
    exists_: bool = Field(alias="$exists")


# Evaluation operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/regex/
#
# Note: "$contains" is NOT a formal MongoDB operator, but the backend recognizes and
# executes it as a substring-match filter.
class Regex(BaseOp):
    regex_: str = Field(alias="$regex")  #: The regex expression to match against.


class Contains(BaseOp):
    contains_: str = Field(alias="$contains")  #: The substring to match against.


And.model_rebuild()
Or.model_rebuild()
Not.model_rebuild()
Lt.model_rebuild()
Gt.model_rebuild()
Lte.model_rebuild()
Gte.model_rebuild()
Eq.model_rebuild()
Ne.model_rebuild()
In.model_rebuild()
NotIn.model_rebuild()
Exists.model_rebuild()
Regex.model_rebuild()
Contains.model_rebuild()


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


KnownOp = Union[
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
UnknownOp = Dict[str, Any]

# for type annotations
Op = Union[KnownOp, UnknownOp]
# for runtime type checks
OpTypes: tuple[type, ...] = (*get_args(KnownOp), dict)
