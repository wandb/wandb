"""Types for handling logical operations for filter/query expressions.

MongoDB specs: https://www.mongodb.com/docs/manual/reference/operator/query-logical/
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from .base import Op

if TYPE_CHECKING:
    from .filter import AnyExpr


# Variadic logical ops
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


# Unary logical ops
class Not(Op):
    OP: ClassVar[str] = "$not"
    other: AnyExpr
