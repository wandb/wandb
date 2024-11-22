"""Convenience functions to make constructing/composing operators less verbose and tedious."""

from __future__ import annotations

from typing import Iterable

from .comparison import Eq, Gt, Gte, In, Lt, Lte, Ne, NotIn, ScalarT
from .evaluation import Contains, Regex
from .filter import AnyExpr
from .logic import And, Nor, Not, Or


def or_(*exprs: AnyExpr) -> Or:
    return Or(other=exprs)


def and_(*exprs: AnyExpr) -> And:
    return And(other=exprs)


def nor_(*exprs: AnyExpr) -> Nor:
    return Nor(other=exprs)


def not_(expr: AnyExpr) -> Not:
    return Not(other=expr)


def gt(val: ScalarT) -> Gt:
    return Gt(other=val)


def gte(val: ScalarT) -> Gte:
    return Gte(other=val)


def lt(val: ScalarT) -> Lt:
    return Lt(other=val)


def lte(val: ScalarT) -> Lte:
    return Lte(other=val)


def eq(val: ScalarT) -> Eq:
    return Eq(other=val)


def ne(val: ScalarT) -> Ne:
    return Ne(other=val)


# ------------------------------------------------------------------------------
def in_(vals: Iterable[ScalarT]) -> In:
    return In(other=vals)


def not_in(vals: Iterable[ScalarT]) -> NotIn:
    return NotIn(other=vals)


# ------------------------------------------------------------------------------
def regex_match(pattern: str) -> Regex:
    return Regex(other=pattern)


def contains(substr: str) -> Contains:
    return Contains(other=substr)
