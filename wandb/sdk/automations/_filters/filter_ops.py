"""Types for parsing, serializing, and defining MongoDB-compatible operators for filter/query expressions.

MongoDB specs: https://www.mongodb.com/docs/manual/reference/operator/query-logical/
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Union

from .base import Op

if TYPE_CHECKING:
    from .filter_expr import AnyExpr


Scalar = Union[str, int, float, bool, None]


# Logical operators (variadic)
class And(Op):
    """Parsed `$and` operator, which may also be interpreted as an "all_of" operator."""

    OP: ClassVar[str] = "$and"
    other: tuple[AnyExpr, ...] = ()  # Ok since tuples are immutable


class Or(Op):
    """Parsed `$or` operator, which may also be interpreted as an "any_of" operator."""

    OP: ClassVar[str] = "$or"
    other: tuple[AnyExpr, ...] = ()  # Ok since tuples are immutable


class Nor(Op):
    """Parsed `$nor` operator, which may also be interpreted as a "not_any" operator."""

    OP: ClassVar[str] = "$nor"
    other: tuple[AnyExpr, ...] = ()  # Ok since tuples are immutable


# Logical operators (unary)
class Not(Op):
    """Parsed `$not` operator."""

    OP: ClassVar[str] = "$not"
    other: AnyExpr


# ------------------------------------------------------------------------------
# Comparison operators
class Lt(Op):
    OP: ClassVar[str] = "$lt"
    other: Scalar


class Gt(Op):
    OP: ClassVar[str] = "$gt"
    other: Scalar


class Lte(Op):
    OP: ClassVar[str] = "$lte"
    other: Scalar


class Gte(Op):
    OP: ClassVar[str] = "$gte"
    other: Scalar


class Eq(Op):
    OP: ClassVar[str] = "$eq"
    other: Scalar


class Ne(Op):
    OP: ClassVar[str] = "$ne"
    other: Scalar


class In(Op):
    OP: ClassVar[str] = "$in"
    other: tuple[Scalar, ...]


class NotIn(Op):
    OP: ClassVar[str] = "$nin"
    other: tuple[Scalar, ...]


# ------------------------------------------------------------------------------
# Evaluation operators
class Regex(Op):
    OP: ClassVar[str] = "$regex"
    other: str  #: The regex expression to match against.


class Contains(Op):
    # Not an actual MongoDB operator, but the backend treats this as a substring-match filter.
    OP: ClassVar[str] = "$contains"
    other: str  #: The substring to match against.
