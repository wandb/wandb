from __future__ import annotations

from typing import ClassVar, Union

from wandb.sdk.automations._filters.base import Op

ValueT = Union[str, int, float]


class Lt(Op):
    op: ClassVar[str] = "$lt"

    inner_operand: ValueT


class Gt(Op):
    op: ClassVar[str] = "$gt"

    inner_operand: ValueT


class Lte(Op):
    op: ClassVar[str] = "$lte"

    inner_operand: ValueT


class Gte(Op):
    op: ClassVar[str] = "$gte"

    inner_operand: ValueT


class Eq(Op):
    op: ClassVar[str] = "$eq"

    inner_operand: ValueT


class Ne(Op):
    op: ClassVar[str] = "$ne"

    inner_operand: ValueT


class In(Op):
    op: ClassVar[str] = "$in"

    inner_operand: list[ValueT]


class NotIn(Op):
    op: ClassVar[str] = "$nin"

    inner_operand: list[ValueT]
