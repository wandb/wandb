from __future__ import annotations

from functools import singledispatch
from itertools import chain
from typing import Any, Final, TypeVar

from wandb._pydantic import pydantic_isinstance, to_json

from ._filters import And, FilterExpr, In, Nor, Not, NotIn, Op, Or

T = TypeVar("T")

# Maps MongoDB comparison operators -> Python literal (str) representations
MONGO2PY_OPS: Final[dict[str, str]] = {
    "$eq": "==",
    "$ne": "!=",
    "$gt": ">",
    "$lt": "<",
    "$gte": ">=",
    "$lte": "<=",
}
# Reverse mapping from Python literal (str) -> MongoDB operator key
PY2MONGO_OPS: Final[dict[str, str]] = {v: k for k, v in MONGO2PY_OPS.items()}


def validate_scope(v: Any) -> Any:
    """Convert a familiar wandb `Project` or `ArtifactCollection` object to an automation scope."""
    from wandb.apis.public import ArtifactCollection, Project

    from .scopes import ArtifactCollectionScope, ProjectScope

    if isinstance(v, Project):
        return ProjectScope(id=v.id, name=v.name)
    if isinstance(v, ArtifactCollection):
        return ArtifactCollectionScope(id=v.id, name=v.name)
    return v


def ensure_json(v: Any) -> Any:
    """Validate that a value is a serialized JSON object."""
    # the Json type expects to parse a JSON-serialized object, so re-serialize it first if needed
    return v if isinstance(v, (str, bytes)) else to_json(v)


@singledispatch
def simplify_ops(op: Op | FilterExpr) -> Op | FilterExpr:
    """Simplify a MongoDB filter by removing and unnesting redundant operators."""
    return op


@simplify_ops.register
def _(op: And) -> Op:
    # {"$and": []} -> {"$and": []}
    if not (inner := op.and_):
        return op

    # {"$and": [only_op]} -> only_op
    if len(inner) == 1:
        return simplify_ops(inner[0])

    # {"$and": [op, {"$and": [op2, ...]}]} -> {"$and": [op, op2, ...]}
    new_inner = chain.from_iterable(
        x.and_ if pydantic_isinstance(x, And) else (x,) for x in inner
    )
    return And(and_=map(simplify_ops, new_inner))


@simplify_ops.register
def _(op: Or) -> Op:
    # {"$or": []} -> {"$or": []}
    if not (inner := op.or_):
        return op

    # {"$or": [only_op]} -> only_op
    if len(inner) == 1:
        return simplify_ops(inner[0])

    # {"$or": [op, {"$or": [op2, ...]}]} -> {"$or": [op, op2, ...]}
    new_inner = chain.from_iterable(
        x.or_ if pydantic_isinstance(x, Or) else (x,) for x in inner
    )
    return Or(or_=map(simplify_ops, new_inner))


@simplify_ops.register
def _(op: Not) -> Op:
    inner = op.not_

    # {"$not": {"$not": op}} -> op
    if isinstance(inner, Not):
        return simplify_ops(inner.not_)

    # {"$not": {"$or": [op, ...]}} -> {"$nor": [op, ...]}
    if isinstance(inner, Or):
        return Nor(nor_=map(simplify_ops, inner.or_))

    # {"$not": {"$nor": [op, ...]}} -> {"$or": [op, ...]}
    if isinstance(inner, Nor):
        return Or(or_=map(simplify_ops, inner.nor_))

    # {"$not": {"$in": [op, ...]}} -> {"$nin": [op, ...]}
    if isinstance(inner, In):
        return NotIn(nin_=inner.in_)

    # {"$not": {"$nin": [op, ...]}} -> {"$in": [op, ...]}
    if isinstance(inner, NotIn):
        return In(in_=inner.not_in_)

    return op
