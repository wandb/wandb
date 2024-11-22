"""Convenience functions to make constructing/composing operators less verbose and tedious."""

from __future__ import annotations

from typing import Any, Iterable

from ._operators import (
    And,
    Contains,
    Eq,
    Gt,
    Gte,
    In,
    Lt,
    Lte,
    Ne,
    Nor,
    Not,
    NotIn,
    Or,
    Regex,
    Scalar,
)


def or_(*exprs: Any) -> Or:
    return Or(other=exprs)


def and_(*exprs: Any) -> And:
    return And(other=exprs)


def nor_(*exprs: Any) -> Nor:
    return Nor(other=exprs)


def not_(expr: Any) -> Not:
    return Not(other=expr)


def gt(val: Scalar) -> Gt:
    return Gt(other=val)


def gte(val: Scalar) -> Gte:
    return Gte(other=val)


def lt(val: Scalar) -> Lt:
    return Lt(other=val)


def lte(val: Scalar) -> Lte:
    return Lte(other=val)


def eq(val: Scalar) -> Eq:
    return Eq(other=val)


def ne(val: Scalar) -> Ne:
    return Ne(other=val)


# ------------------------------------------------------------------------------
def in_(vals: Iterable[Scalar]) -> In:
    return In(other=vals)


def not_in(vals: Iterable[Scalar]) -> NotIn:
    return NotIn(other=vals)


# ------------------------------------------------------------------------------
def regex_match(pattern: str) -> Regex:
    return Regex(other=pattern)


def contains(substr: str) -> Contains:
    return Contains(other=substr)
