from __future__ import annotations

from abc import ABC
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import RootModel, model_serializer

from wandb.sdk.automations.base import Base


class Expr(Base, ABC):
    """Base class for expressions."""

    def __or__(self, other: ExprT) -> Or:
        raise NotImplementedError

    def __and__(self, other: ExprT) -> And:
        raise NotImplementedError

    def __invert__(self) -> Not:
        raise NotImplementedError

    def __lt__(self, other: ExprT) -> Lt:
        raise NotImplementedError

    def __gt__(self, other: ExprT) -> Gt:
        raise NotImplementedError

    def __le__(self, other: ExprT) -> Lte:
        raise NotImplementedError

    def __ge__(self, other: ExprT) -> Gte:
        raise NotImplementedError

    def __eq__(self, other: ExprT) -> Eq:
        raise NotImplementedError

    def __ne__(self, other: ExprT) -> Ne:
        raise NotImplementedError


ExprT = TypeVar("ExprT", bound=Expr)


# ------------------------------------------------------------------------------
class FieldPredicate(RootModel[dict[str, Expr]]):
    pass


# ------------------------------------------------------------------------------
class Op(StrEnum):
    OR = "$or"
    AND = "$and"
    NOT = "$not"


# ------------------------------------------------------------------------------
class LogicalOp(Expr):
    """Base type for logical operator expressions.

    MongoDB specs: https://www.mongodb.com/docs/manual/reference/operator/query-logical/
    """

    key: str
    expressions: list[ExprT]


class Or(Expr):
    key: Literal["$or"] = "$or"
    expressions: list[ExprT]

    @model_serializer(when_used="always")
    def to_mongo(self) -> dict[str, Any]:
        return {self.key: [expr.model_dump() for expr in self.expressions]}


class And(Expr):
    key: Literal["$and"] = "$and"
    expressions: list[ExprT]

    @model_serializer(when_used="always")
    def to_mongo(self) -> dict[str, Any]:
        return {self.key: [expr.model_dump() for expr in self.expressions]}


class Not(Expr):
    key: Literal["$not"] = "$not"
    expression: ExprT

    @model_serializer(when_used="always")
    def to_mongo(self) -> dict[str, Any]:
        return {self.key: self.expression.model_dump()}


# ------------------------------------------------------------------------------
class Lt(Expr):
    pass  # TODO


class Gt(Expr):
    pass  # TODO


class Lte(Expr):
    pass  # TODO


class Gte(Expr):
    pass  # TODO


class Eq(Expr):
    pass  # TODO


class Ne(Expr):
    pass  # TODO


class In(Expr):
    pass  # TODO
