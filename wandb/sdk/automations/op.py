from __future__ import annotations

from abc import ABC
from collections.abc import Iterable
from typing import TypeVar, Union

from pydantic import Field, RootModel
from pydantic._internal import _repr

from wandb.sdk.automations.base import Base


class Op(Base, ABC):
    """Base class for operators in expressions."""

    def __or__(self, other: OpT) -> Or:
        return Or(exprs=[self, other])

    def __and__(self, other: OpT) -> And:
        return And(exprs=[self, other])

    def __invert__(self) -> Op:
        return Not(expr=self)

    # # ------------------------------------------------------------------------------
    # def __lt__(self, other: ValueT) -> Lt:
    #     raise NotImplementedError
    #
    # def __gt__(self, other: ValueT) -> Gt:
    #     raise NotImplementedError
    #
    # def __le__(self, other: ValueT) -> Lte:
    #     raise NotImplementedError
    #
    # def __ge__(self, other: ValueT) -> Gte:
    #     raise NotImplementedError
    #
    # # ------------------------------------------------------------------------------
    # def __eq__(self, other: ValueT) -> Eq:
    #     raise NotImplementedError
    #
    # def __ne__(self, other: ValueT) -> Ne:
    #     raise NotImplementedError


OpT = TypeVar("OpT", bound=Op)

#: Placeholder - TODO: make these variadic depending on compared field/expression
ValueT = TypeVar("ValueT")


# ------------------------------------------------------------------------------
# MongoDB specs: https://www.mongodb.com/docs/manual/reference/operator/query-logical/
class LogicalOp(Op):
    pass


class Not(LogicalOp):
    expr: AnyExpr = Field(alias="$not")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.expr


class And(LogicalOp):
    exprs: list[AnyExpr] = Field(alias="$and")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield from ((None, x) for x in self.exprs)


class Or(LogicalOp):
    exprs: list[AnyExpr] = Field(alias="$or")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield from ((None, x) for x in self.exprs)


class Nor(LogicalOp):
    exprs: list[AnyExpr] = Field(alias="$nor")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield from ((None, x) for x in self.exprs)


def not_(expr: AnyExpr) -> Not:
    return Not(expr=expr)


def all_of(exprs: Iterable[AnyExpr]) -> And:
    return And(exprs=exprs)


def any_of(exprs: Iterable[AnyExpr]) -> Or:
    return And(exprs=exprs)


def none_of(exprs: Iterable[AnyExpr]) -> Nor:
    return Nor(exprs=exprs)


# ------------------------------------------------------------------------------
class CompareOp(Op):
    pass


class Lt(CompareOp):
    val: ValueT = Field(alias="$lt")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.val


class Gt(CompareOp):
    val: ValueT = Field(alias="$gt")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.val


class Lte(CompareOp):
    val: ValueT = Field(alias="$lte")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.val


class Gte(CompareOp):
    val: ValueT = Field(alias="$gte")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.val


class Eq(CompareOp):
    val: ValueT = Field(alias="$eq")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.val


class Ne(CompareOp):
    val: ValueT = Field(alias="$ne")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.val


class In(CompareOp):
    vals: set[ValueT] = Field(alias="$in")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield from ((None, v) for v in self.vals)


class Nin(CompareOp):
    vals: set[ValueT] = Field(alias="$nin")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield from ((None, v) for v in self.vals)


# ------------------------------------------------------------------------------
class EvalOp(Op):
    pass


class Regex(EvalOp):
    regex: str = Field(alias="$regex")
    options: str | None = Field(None, alias="$options")

    def __repr_args__(self) -> _repr.ReprArgs:
        yield None, self.regex


# ------------------------------------------------------------------------------
class QueryExpr(RootModel):
    root: dict[str, AnyExpr]

    def __repr_args__(self) -> _repr.ReprArgs:
        yield from ((field, expr) for field, expr in self.root.items())


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
    QueryExpr,
]
