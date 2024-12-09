from __future__ import annotations

from typing import ClassVar, Union

from .base import Op

ScalarT = Union[str, int, float]


class Lt(Op):
    OP: ClassVar[str] = "$lt"
    other: ScalarT


class Gt(Op):
    OP: ClassVar[str] = "$gt"
    other: ScalarT


class Lte(Op):
    OP: ClassVar[str] = "$lte"
    other: ScalarT


class Gte(Op):
    OP: ClassVar[str] = "$gte"
    other: ScalarT


class Eq(Op):
    OP: ClassVar[str] = "$eq"
    other: ScalarT


class Ne(Op):
    OP: ClassVar[str] = "$ne"
    other: ScalarT


class In(Op):
    OP: ClassVar[str] = "$in"
    other: tuple[ScalarT, ...]


class NotIn(Op):
    OP: ClassVar[str] = "$nin"
    other: tuple[ScalarT, ...]
