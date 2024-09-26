"""Convenience functions to make constructing/composing operators less verbose and tedious."""

from __future__ import annotations

from typing import Iterable, Iterator

from wandb.sdk.automations._ops.base import Op
from wandb.sdk.automations._ops.comparison import Eq, Gt, Gte, Lt, Lte, Ne, ValueT
from wandb.sdk.automations._ops.evaluation import Regex
from wandb.sdk.automations._ops.logic import And, Nor, Not, Or
from wandb.sdk.automations._ops.op import AnyExpr, ExpressionField


def _iter_flattened(*exprs: Op | Iterable[Op]) -> Iterator[Op]:
    for expr in exprs:
        if isinstance(expr, Op):
            yield expr
        else:
            yield from expr


def or_(*exprs: AnyExpr | Iterable[AnyExpr]) -> Or:
    all_exprs = list(_iter_flattened(*exprs))
    return Or(exprs=all_exprs)


def and_(*exprs: AnyExpr | Iterable[AnyExpr]) -> And:
    all_exprs = list(_iter_flattened(*exprs))
    return And(exprs=all_exprs)


def none_of(*exprs: AnyExpr | Iterable[AnyExpr]) -> Nor:
    all_exprs = list(_iter_flattened(*exprs))
    return Nor(exprs=all_exprs)


def not_(expr: AnyExpr) -> Not:
    return Not(expr=expr)


def gt(val: ValueT) -> Gt:
    return Gt(val=val)


def gte(val: ValueT) -> Gte:
    return Gte(val=val)


def lt(val: ValueT) -> Lt:
    return Lt(val=val)


def lte(val: ValueT) -> Lte:
    return Lte(val=val)


def eq(val: ValueT) -> Eq:
    return Eq(val=val)


def ne(val: ValueT) -> Ne:
    return Ne(val=val)


# ------------------------------------------------------------------------------
def regex(pattern: str) -> Regex:
    return Regex(regex=pattern)


# ------------------------------------------------------------------------------
def on_field(field: str) -> ExpressionField:
    # When/if needed for greater flexiblity:
    # handle when class attributes e.g. `Artifact.tags/aliases` are passed directly as well
    return ExpressionField(field)
