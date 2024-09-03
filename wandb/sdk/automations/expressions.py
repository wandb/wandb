from __future__ import annotations

from abc import ABC
from typing import TypeVar, Union

from pydantic import Field, RootModel
from pydantic._internal import _repr

from wandb.sdk.automations.base import Base


class Expr(Base, ABC):
    """Base class for expressions."""

    pass

    # def __or__(self, other: ExprT) -> Or:
    #     return Or(
    #         or_=[
    #             *(self.or_ if isinstance(self, Or) else [self]),
    #             *(other.or_ if isinstance(other, Or) else [other]),
    #         ]
    #     )
    #
    # def __and__(self, other: ExprT) -> And:
    #     return And(
    #         and_=[
    #             *(self.and_ if isinstance(self, And) else [self]),
    #             *(other.and_ if isinstance(other, And) else [other]),
    #         ]
    #     )
    #
    # def __invert__(self) -> Expr:
    #     if isinstance(self, Not):
    #         return self.not_
    #     if isinstance(self, In):
    #         return Nin(nin_=self.in_)
    #     return Not(not_=self)

    # # ------------------------------------------------------------------------------
    # def __lt__(self, other: NumT) -> Lt:
    #     raise NotImplementedError
    #
    # def __gt__(self, other: NumT) -> Gt:
    #     raise NotImplementedError
    #
    # def __le__(self, other: NumT) -> Lte:
    #     raise NotImplementedError
    #
    # def __ge__(self, other: NumT) -> Gte:
    #     raise NotImplementedError
    #
    # # ------------------------------------------------------------------------------
    # def __eq__(self, other: ValueT) -> Eq:
    #     raise NotImplementedError
    #
    # def __ne__(self, other: ValueT) -> Ne:
    #     raise NotImplementedError


ExprT = TypeVar("ExprT", bound=Expr)

#: Placeholder - TODO: make these variadic depending on compared field/expression
NumT = Union[int, float]
ValueT = TypeVar("ValueT")


# ------------------------------------------------------------------------------
# MongoDB specs: https://www.mongodb.com/docs/manual/reference/operator/query-logical/
class Or(Expr):
    or_: list[AnyExpr] = Field(alias="$or")


class And(Expr):
    and_: list[AnyExpr] = Field(alias="$and")


class Not(Expr):
    not_: AnyExpr = Field(alias="$not")


# ------------------------------------------------------------------------------
class Regex(Expr):
    regex: str = Field(alias="$regex")
    options: str | None = Field(None, alias="$options")


# ------------------------------------------------------------------------------
class Lt(Expr):
    lt_: NumT = Field(alias="$lt")


class Gt(Expr):
    gt_: NumT = Field(alias="$gt")


class Lte(Expr):
    lte_: NumT = Field(alias="$lte")


class Gte(Expr):
    gte_: NumT = Field(alias="$gte")


# ------------------------------------------------------------------------------
class Eq(Expr):
    eq_: ValueT = Field(alias="$eq")


class Ne(Expr):
    ne_: ValueT = Field(alias="$ne")


# ------------------------------------------------------------------------------
class In(Expr):
    in_: list[ValueT] = Field(alias="$in")


class Nin(Expr):
    nin_: list[ValueT] = Field(alias="$nin")


# ------------------------------------------------------------------------------
class FieldPredicate(RootModel):
    root: dict[str, AnyExpr]

    def __repr_args__(self) -> _repr.ReprArgs:
        yield from self.root.items()


class MetricPredicate(FieldPredicate):
    pass


AnyExpr = Union[
    Or,
    And,
    Not,
    Regex,
    Lt,
    Gt,
    Lte,
    Gte,
    Eq,
    Ne,
    In,
    Nin,
    FieldPredicate,
]
