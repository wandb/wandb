"""Helpers for parsing and transforming MongoDB expressions.

If a function is defined here, it's an internal helper that we deliberately
don't expose as instnace methods on filter types for now.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import singledispatch
from itertools import chain
from typing import Any, cast

from typing_extensions import assert_never

from .expressions import FilterExpr, MongoLikeFilter
from .operators import (
    And,
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

_OP_KEY_REGEX: re.Pattern[str] = re.compile(r"^\$\w+$", flags=re.ASCII)
"""Regex pattern for MongoDB operator keys."""


def parse_filter(raw: dict[str, Any]) -> MongoLikeFilter:
    """Parse a raw MongoDB-style filter dict into a typed MongoDB filter expression."""
    match raw:
        case dict() if len(raw) < 1:
            return raw
        case dict() if len(raw) > 1:
            # Multiple root predicates imply "$and".
            return And(exprs=(parse_filter({k: v}) for k, v in raw.items()))

        # Below this, we're guaranteed a length-1 dict, so we can drop length guards.
        case {"$and": exprs}:
            return And(exprs=map(parse_filter, exprs))
        case {"$or": exprs}:
            return Or(exprs=map(parse_filter, exprs))
        case {"$nor": exprs}:
            return Nor(exprs=map(parse_filter, exprs))
        case {"$not": expr}:
            return Not(expr=parse_filter(expr))

        case dict():
            ((key, obj),) = raw.items()

            if key.startswith("$"):
                return raw  # Unknown operator dict
            if isinstance(obj, dict):
                return FilterExpr.model_validate(raw)
            return FilterExpr(field=key, op=Eq(val=obj))
        case _:
            assert_never(raw)


def iter_fields(node: MongoLikeFilter) -> Iterator[str]:
    """Iterate over the field names referenced in a MongoDB filter.

    Unknown operators are left untouched because their operands may not be filters.
    """
    match node:
        case FilterExpr(field=field):
            yield field
        case BaseVariadicLogicalOp(exprs=exprs):
            yield from chain.from_iterable(map(iter_fields, exprs))
        case Not(expr=expr):
            yield from iter_fields(expr)


@singledispatch
def simplify_expr(expr: MongoLikeFilter) -> MongoLikeFilter:
    """Simplify a MongoDB filter by removing and unnesting redundant operators."""
    return expr  # default implementation is a no-op


# singledispatch on the abstract parent dispatches to all And/Or/Nor subclasses
@simplify_expr.register
def _(op: BaseVariadicLogicalOp) -> MongoLikeFilter:  # type: ignore[misc]
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
    # cls is always one of And/Or/Nor — concrete subclasses of BaseVariadicLogicalOp
    # that *are* in the MongoLikeFilter union, but type checkers can't see this
    # through the abstract `type(op)` capture.
    return cast(MongoLikeFilter, cls(exprs=exprs))


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
