"""Helpers for parsing and transforming MongoDB expressions.

If a function is defined here, it's an internal helper that we deliberately
don't expose as instnace methods on filter types for now.
"""

from __future__ import annotations

from functools import singledispatch
from typing import Iterator

from .expressions import FilterExpr, MongoLikeFilter
from .operators import (
    BaseVariadicLogicalOp,
    Eq,
    Exists,
    Gt,
    Gte,
    In,
    Lt,
    Lte,
    Ne,
    Nor,
    Not,
    NotIn,
    Op,
    Or,
)


@singledispatch
def simplify_expr(expr: MongoLikeFilter) -> MongoLikeFilter:
    """Simplify a MongoDB filter by removing and unnesting redundant operators."""
    return expr  # default implementation is a no-op


@simplify_expr.register
def _(op: BaseVariadicLogicalOp) -> MongoLikeFilter:
    """Simplify an `And/Or/Nor` operator by removing and unnesting redundant expressions.

    This will flatten the operator's inner expressions and simplify them recursively,
    e.g.:
    - `And(op1, And(op2, ...)) -> And(op1, op2, ...)`
    - `Or(op1, Or(op2, ...)) -> Or(op1, op2, ...)`

    Note that unnested empty operators are preserved, e.g.
    - `And() -> And()`
    - `Or() -> Or()`

    However, nested empty operators are flattened, e.g.:
    - `And(And(), And()) -> And()`
    - `Or(Or(), Or()) -> Or()`

    Single inner expressions are unnested, e.g.:
    - `And(a) -> a`
    - `Or(a) -> a`
    """
    cls = type(op)
    # Flatten and simplify the operator's inner expressions.
    if len(exprs := [simplify_expr(x) for x in flatten_inner(op, cls)]) == 1:
        return exprs[0]  # Unnest single inner expressions.
    return cls(exprs=exprs)


@simplify_expr.register
def _(op: Not) -> MongoLikeFilter:
    """Simplify a `Not` operator by removing and unnesting redundant expressions.

    This will invert the inner expression if possible and otherwise remove nested
    `Not` operators, e.g.:
    - `Not(Not(a)) -> a`
    - `Not(Or(a, b)) -> Nor(a, b)`
    - `Not(Nor(a, b)) -> Or(a, b)`
    - `Not(In(a, b)) -> NotIn(a, b)`
    - `Not(NotIn(a, b)) -> In(a, b)`
    """
    # TODO: Find a more efficient way to apply custom __invert__ impls
    if isinstance(
        expr := op.expr, (Not, Or, Nor, In, NotIn, Eq, Ne, Lt, Lte, Gt, Gte, Exists)
    ):
        return simplify_expr(~expr)
    return Not(expr=simplify_expr(expr))


def flatten_inner(
    op: BaseVariadicLogicalOp,
    parent_cls: type[BaseVariadicLogicalOp],
) -> Iterator[FilterExpr | Op]:
    """Iterates over an `And/Or/Nor` operator's flattened inner expressions."""
    for x in op.exprs:
        yield from (flatten_inner(x, parent_cls) if isinstance(x, parent_cls) else (x,))
