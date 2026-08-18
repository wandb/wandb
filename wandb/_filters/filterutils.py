"""Helpers for parsing and transforming MongoDB expressions.

If a function is defined here, it's an internal helper that we deliberately
don't expose as instance methods on filter types for now.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import singledispatch
from itertools import chain

from pydantic import JsonValue

from .expressions import FilterExpr, MongoLikeFilter
from .operators import (
    KEY_TO_OP,
    And,
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
    Or,
)


def parse_filter(raw: dict[str, JsonValue]) -> MongoLikeFilter:
    """Parse a raw MongoDB-style filter, leaving unknown operators opaque."""
    match list(raw.items()):
        case []:
            return raw
        case [(k, _)] if op_cls := KEY_TO_OP.get(k):
            return op_cls.model_validate(raw)
        case [(k, _)] if k.startswith("$"):
            # This looks like an unrecognized operator, so leave it opaque.
            return raw
        case [(k, dict())]:
            return FilterExpr.model_validate(raw)
        case [(k, v)]:
            # An ordinary non-dict operand implies an equality expression.
            return FilterExpr.model_validate({k: {"$eq": v}})
        case items:  # Multiple root predicates imply "$and".
            return And.model_validate({"$and": [{k: v} for k, v in items]})


def iter_fields(expr: MongoLikeFilter) -> Iterator[str]:
    """Iterate over the field names referenced in a MongoDB filter.

    Unknown operators are left untouched because their operands may not be filters.
    """
    match expr:
        case FilterExpr(field=field):
            yield field
        case And(exprs=exprs) | Or(exprs=exprs) | Nor(exprs=exprs):
            yield from chain.from_iterable(map(iter_fields, exprs))
        case Not(expr=expr):
            yield from iter_fields(expr)


@singledispatch
def simplify_expr(expr: MongoLikeFilter) -> MongoLikeFilter:
    """Simplify a MongoDB filter by removing and unnesting redundant operators."""
    return expr  # default implementation is a no-op


@simplify_expr.register(And)
@simplify_expr.register(Or)
@simplify_expr.register(Nor)
def _(op: And | Or | Nor) -> MongoLikeFilter:
    """Simplify an `And/Or/Nor` operator by removing and unnesting redundant expressions.

    This will flatten the inner expressions and simplify recursively:
    - `And(op1, And(op2, ...)) -> And(op1, op2, ...)`
    - `Or(op1, Or(op2, ...)) -> Or(op1, op2, ...)`

    Unnested empty operators are preserved:
    - `And() -> And()`
    - `Or() -> Or()`

    Nested empty operators are flattened:
    - `And(And(), And()) -> And()`
    - `Or(Or(), Or()) -> Or()`

    Single inner expressions are unnested:
    - `And(a) -> a`
    - `Or(a) -> a`
    """
    cls = type(op)
    # Flatten and simplify the operator's inner expressions.
    match exprs := [simplify_expr(x) for x in flatten_inner(op, cls)]:
        case [only_child]:  # Unnest single inner expressions.
            return only_child
        case _:
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
    op: And | Or | Nor,
    parent_cls: type[And | Or | Nor],
) -> Iterator[MongoLikeFilter]:
    """Iterates over an `And/Or/Nor` operator's flattened inner expressions."""
    for x in op.exprs:
        yield from (flatten_inner(x, parent_cls) if type(x) is parent_cls else (x,))
