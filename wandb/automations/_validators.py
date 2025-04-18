from __future__ import annotations

from functools import singledispatch
from itertools import chain
from typing import Any, TypeVar

from ._filters import And, FilterExpr, In, Nor, Not, NotIn, Op, Or

T = TypeVar("T")


def validate_scope(v: Any) -> Any:
    """Convert a familiar wandb `Project` or `ArtifactCollection` object to an automation scope."""
    from wandb.apis.public import ArtifactCollection, Project

    from .scopes import ProjectScope, _ArtifactPortfolioScope, _ArtifactSequenceScope

    if isinstance(v, Project):
        return ProjectScope(id=v.id, name=v.name)
    if isinstance(v, ArtifactCollection):
        cls = _ArtifactSequenceScope if v.is_sequence() else _ArtifactPortfolioScope
        return cls(id=v.id, name=v.name)
    return v


@singledispatch
def simplify_op(op: Op | FilterExpr) -> Op | FilterExpr:
    """Simplify a MongoDB filter by removing and unnesting redundant operators."""
    return op


@simplify_op.register
def _(op: And) -> Op:
    # {"$and": []} -> {"$and": []}
    if not (args := op.and_):
        return op

    # {"$and": [op]} -> op
    if len(args) == 1:
        return simplify_op(args[0])

    # {"$and": [op, {"$and": [op2, ...]}]} -> {"$and": [op, op2, ...]}
    flattened = chain.from_iterable(x.and_ if isinstance(x, And) else [x] for x in args)
    return And(and_=map(simplify_op, flattened))


@simplify_op.register
def _(op: Or) -> Op:
    # {"$or": []} -> {"$or": []}
    if not (args := op.or_):
        return op

    # {"$or": [op]} -> op
    if len(args) == 1:
        return simplify_op(args[0])

    # {"$or": [op, {"$or": [op2, ...]}]} -> {"$or": [op, op2, ...]}
    flattened = chain.from_iterable(x.or_ if isinstance(x, Or) else [x] for x in args)
    return Or(or_=map(simplify_op, flattened))


@simplify_op.register
def _(op: Not) -> Op:
    inner = op.not_

    # {"$not": {"$not": op}} -> op
    # {"$not": {"$or": [op, ...]}} -> {"$nor": [op, ...]}
    # {"$not": {"$nor": [op, ...]}} -> {"$or": [op, ...]}
    # {"$not": {"$in": [op, ...]}} -> {"$nin": [op, ...]}
    # {"$not": {"$nin": [op, ...]}} -> {"$in": [op, ...]}
    if isinstance(inner, (Not, Or, Nor, In, NotIn)):
        return simplify_op(~inner)
    return Not(not_=simplify_op(inner))
