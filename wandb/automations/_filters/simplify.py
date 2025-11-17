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
    In,
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
    typ = type(op)

    # Flatten the operator's inner expressions and simplify them recursively.
    # This will ensure e.g.:
    #   `{"$and": [op, {"$and": [op2, ...]}]} -> {"$and": [op, op2, ...]}`
    #   `{"$or": [op, {"$or": [op2, ...]}]} -> {"$or": [op, op2, ...]}`
    exprs = list(simplify_expr(x) for x in flatten_exprs(op))

    # if not exprs:
    #     return op

    # "Unnest" single expressions inside $and/$or operators, e.g.:
    #   `{"$and": [expr]} -> expr`
    #   `{"$or": [expr]} -> expr`
    if len(exprs) == 1:
        return simplify_expr(exprs[0])

    # Note that the result is empty for empty $and/$or operators, e.g.:
    #   `{"$and":[]}`
    #   `{"$or":[]}`
    return typ(exprs=exprs)


@simplify_expr.register
def _(op: Not) -> MongoLikeFilter:
    # {"$not": {"$not": op}} -> op
    # {"$not": {"$or": [op, ...]}} -> {"$nor": [op, ...]}
    # {"$not": {"$nor": [op, ...]}} -> {"$or": [op, ...]}
    # {"$not": {"$in": [op, ...]}} -> {"$nin": [op, ...]}
    # {"$not": {"$nin": [op, ...]}} -> {"$in": [op, ...]}
    if isinstance(expr := op.expr, (Not, Or, Nor, In, NotIn, Eq, Ne, Exists)):
        return simplify_expr(~expr)
    return Not(expr=simplify_expr(expr))


def flatten_exprs(op: BaseVariadicLogicalOp) -> Iterator[FilterExpr | Op]:
    typ = type(op)
    for x in op.exprs:
        if isinstance(x, typ):
            yield from flatten_exprs(x)
        else:
            yield x
