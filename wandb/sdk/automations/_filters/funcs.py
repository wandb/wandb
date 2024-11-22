"""Convenience functions to make constructing/composing operators less verbose and tedious."""

from __future__ import annotations

from typing import Iterable

from wandb.sdk.automations._filters.comparison import (
    Eq,
    Gt,
    Gte,
    In,
    Lt,
    Lte,
    Ne,
    NotIn,
    ValueT,
)
from wandb.sdk.automations._filters.evaluation import Regex
from wandb.sdk.automations._filters.filter import AnyExpr, FilterableField
from wandb.sdk.automations._filters.logic import And, Nor, Not, Or


def or_(*exprs: AnyExpr) -> Or:
    return Or(inner_operand=exprs)


def and_(*exprs: AnyExpr) -> And:
    return And(inner_operand=exprs)


def nor_(*exprs: AnyExpr) -> Nor:
    return Nor(inner_operand=exprs)


def not_(expr: AnyExpr) -> Not:
    return Not(inner_operand=expr)


def gt(val: ValueT) -> Gt:
    return Gt(inner_operand=val)


def gte(val: ValueT) -> Gte:
    return Gte(inner_operand=val)


def lt(val: ValueT) -> Lt:
    return Lt(inner_operand=val)


def lte(val: ValueT) -> Lte:
    return Lte(inner_operand=val)


def eq(val: ValueT) -> Eq:
    return Eq(inner_operand=val)


def ne(val: ValueT) -> Ne:
    return Ne(inner_operand=val)


# ------------------------------------------------------------------------------
def in_(vals: Iterable[ValueT]) -> In:
    return In(inner_operand=vals)


def not_in(vals: Iterable[ValueT]) -> NotIn:
    return NotIn(inner_operand=vals)


# ------------------------------------------------------------------------------
def regex_match(pattern: str) -> Regex:
    return Regex(inner_operand=pattern)


# ------------------------------------------------------------------------------
def on_field(field: str) -> FilterableField:
    # When/if needed for greater flexiblity:
    # handle when class attributes e.g. `Artifact.tags/aliases` are passed directly as well
    return FilterableField(field)
