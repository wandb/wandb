from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar, Literal

from pydantic import RootModel
from typing_extensions import Self


class Expr(RootModel, ABC):
    """Base class for expressions."""

    @classmethod
    def from_mongo(cls, obj: dict[str, Any]) -> Self:
        raise NotImplementedError

    def to_mongo(self) -> dict[str, Any]:
        raise NotImplementedError

    def __or__(self, other: Expr) -> Or:
        raise NotImplementedError

    def __and__(self, other: Expr) -> And:
        raise NotImplementedError


# ------------------------------------------------------------------------------
class FieldPredicate(RootModel[dict[str, Expr]]):
    pass


# ------------------------------------------------------------------------------
class LogicalOp(Expr):
    """Base type for logical operator expressions.

    MongoDB specs: https://www.mongodb.com/docs/manual/reference/operator/query-logical/
    """

    _key: ClassVar[str]


class Or(RootModel[dict[Literal["$or"], list[Expr]]], Expr):
    pass
    # _key = "$or"


class And(RootModel[dict[Literal["$and"], list[Expr]]], Expr):
    pass
    # _key = "$and"


class Not(Expr):
    pass  # TODO


# ------------------------------------------------------------------------------
class Lt(Expr):
    pass  # TODO


class Gt(Expr):
    pass  # TODO


class Le(Expr):
    pass  # TODO


class Ge(Expr):
    pass  # TODO


class Eq(Expr):
    pass  # TODO


class Ne(Expr):
    pass  # TODO
