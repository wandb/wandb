"""Helpers for parsing and transforming MongoDB expressions.

If a function is defined here, it's an internal helper that we deliberately
don't expose as instance methods on filter types for now.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from functools import singledispatch
from operator import itemgetter
from typing import Any, cast

from typing_extensions import assert_never

from wandb._strutils import repr_join

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


def transform_fields(
    raw: dict[str, Any],
    *,
    aliases: dict[str, str] | None = None,
    operand_transforms: dict[str, Callable[[Any], Any]] | None = None,
) -> dict[str, Any]:
    """Return a copy of `raw` with ordinary filter fields transformed.

    Args:
        raw: The filter dict to transform.
        aliases: Maps accepted top-level field names to their canonical names.
        operand_transforms: Maps exact field names to callable transformations
            on their inner operands.

    Returns:
        A copy of `raw` with ordinary filter fields transformed.

    Raises:
        ValueError: If `aliases` maps multiple aliases to the same canonical name.
    """
    new_items = tuple(
        _transform_item(*kv, aliases=aliases, operand_transforms=operand_transforms)
        for kv in raw.items()
    )
    result = dict(new_items)

    # Alias definitions are intentionally many-to-one. A collision is invalid
    # only when one filter object uses multiple aliases for the same field.
    if len(result) != len(new_items):
        new_keys = map(itemgetter(0), new_items)
        dup_keys = {key for key, count in Counter(new_keys).items() if count > 1}

        msg = f"Duplicate fields in normalized filter: {repr_join(sorted(dup_keys))}"
        raise ValueError(msg)

    return result


def _transform_item(
    key: str,
    val: Any,
    *,
    aliases: dict[str, str] | None,
    operand_transforms: dict[str, Callable[[Any], Any]] | None,
) -> tuple[str, Any]:
    """Transform one filter item, recursively handling logical operands."""
    match key, val:
        case (("$and" | "$or" | "$nor") as op, list(operands)):
            if not all(isinstance(obj, dict) for obj in operands):
                raise ValueError(f"{op} must contain only filter dictionaries.")
            return key, [
                transform_fields(
                    obj, aliases=aliases, operand_transforms=operand_transforms
                )
                for obj in operands
            ]

        case (("$and" | "$or" | "$nor") as op, _):
            raise ValueError(f"{op} must contain a list of filter dictionaries.")

        case ("$not", dict(operand)):
            return key, transform_fields(
                operand, aliases=aliases, operand_transforms=operand_transforms
            )

        case ("$not", _):
            raise ValueError("$not must contain a filter dictionary.")

        case (str(op), _) if op.startswith("$"):
            return key, val

        case (str(field), _):
            root, sep, suffix = field.partition(".")
            if aliases and not aliases.get(root):
                msg = f"Invalid filter field {root!r}, must be one of: {repr_join(sorted(aliases))}"
                raise ValueError(msg)

            new_root = (aliases or {}).get(root) or root
            new_val = fn(val) if (fn := (operand_transforms or {}).get(field)) else val
            return f"{new_root}{sep}{suffix}", new_val

        case _:
            assert_never((key, val))


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
