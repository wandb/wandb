"""Types that represent operators in MongoDB filter expressions."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple, TypeVar, Union, cast

from pydantic import ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from pydantic_core import to_jsonable_python
from typing_extensions import TypeAlias, get_args, override

from wandb._pydantic import IS_PYDANTIC_V2, Base

# For type annotations and/or narrowing
Scalar = Union[StrictStr, StrictInt, StrictFloat, StrictBool]
# For runtime `isinstance()` checks
ScalarTypes = get_args(Scalar)

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
        return And(and_=[self, other])

    def __invert__(self) -> Not:
        """Syntactic sugar for: `~a` -> `Not(a)`."""
        return Not(not_=self)


# Base class for parsed MongoDB filter/query operators, e.g. `{"$and": [...]}`.
class BaseOp(Base, SupportsLogicalOpSyntax):
    model_config = ConfigDict(
        frozen=True,  # Make pseudo-immutable for easier comparison and hashing
    )

    def __repr__(self) -> str:
        # Display operand as a positional arg
        operands = ", ".join(f"{v!r}" for v in self.model_dump().values())
        return f"{type(self).__name__}({operands})"

    def __rich_repr__(self) -> RichReprResult:  # type: ignore[override]
        # Display operand as a positional arg
        # https://rich.readthedocs.io/en/stable/pretty.html
        for v in self.model_dump().values():
            yield (None, v)

    if not IS_PYDANTIC_V2:
        # Ugly workaround: Pydantic v1 doesn't support 'json' mode to ensure e.g. tuples -> lists
        @override
        def model_dump(self, **kwargs: Any) -> dict[str, Any]:
            return cast(
                Dict[str, Any],
                to_jsonable_python(
                    super().model_dump(**kwargs), by_alias=True, round_trip=True
                ),
            )


# Logical operator(s)
# https://www.mongodb.com/docs/manual/reference/operator/query/and/
# https://www.mongodb.com/docs/manual/reference/operator/query/or/
# https://www.mongodb.com/docs/manual/reference/operator/query/nor/
# https://www.mongodb.com/docs/manual/reference/operator/query/not/
class And(BaseOp):
    and_: TupleOf[Any] = Field(default=(), alias="$and")


class Or(BaseOp):
    or_: TupleOf[Any] = Field(default=(), alias="$or")


class Nor(BaseOp):
    nor_: TupleOf[Any] = Field(default=(), alias="$nor")


class Not(BaseOp):
    not_: Any = Field(alias="$not")


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


class Gt(BaseOp):
    gt_: Scalar = Field(alias="$gt")


class Lte(BaseOp):
    lte_: Scalar = Field(alias="$lte")


class Gte(BaseOp):
    gte_: Scalar = Field(alias="$gte")


class Eq(BaseOp):
    eq_: Scalar = Field(alias="$eq")


class Ne(BaseOp):
    ne_: Scalar = Field(alias="$ne")


class In(BaseOp):
    in_: TupleOf[Scalar] = Field(default=(), alias="$in")


class NotIn(BaseOp):
    nin_: TupleOf[Scalar] = Field(default=(), alias="$nin")


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

AnyOp = Union[KnownOp, UnknownOp]
