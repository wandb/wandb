"""Types for handling logical operations for filter/query expressions.

MongoDB specs: https://www.mongodb.com/docs/manual/reference/operator/query-logical/
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from wandb.sdk.automations._filters.base import Op

if TYPE_CHECKING:
    from wandb.sdk.automations._filters.filter import AnyExpr


# Variadic logical ops
class And(Op):
    """Parsed `$and` operator, which may also be interpreted as an "all_of" operator."""

    op: ClassVar[str] = "$and"
    inner_operand: list[AnyExpr] = Field(default_factory=list)


class Or(Op):
    """Parsed `$or` operator, which may also be interpreted as an "any_of" operator."""

    op: ClassVar[str] = "$or"
    inner_operand: list[AnyExpr] = Field(default_factory=list)


class Nor(Op):
    """Parsed `$nor` operator, which may also be interpreted as a "not_any" operator."""

    op: ClassVar[str] = "$nor"
    inner_operand: list[AnyExpr] = Field(default_factory=list)


# Unary logical ops
class Not(Op):
    op: ClassVar[str] = "$not"

    inner_operand: AnyExpr
