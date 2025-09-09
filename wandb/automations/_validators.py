from __future__ import annotations

from enum import Enum
from functools import singledispatch
from itertools import chain
from typing import Any, TypeVar

from pydantic import BeforeValidator, Json, PlainSerializer
from pydantic_core import PydanticUseDefault
from typing_extensions import Annotated

from wandb._pydantic import to_json

from ._filters import And, FilterExpr, In, Nor, Not, NotIn, Op, Or

T = TypeVar("T")


def ensure_json(v: Any) -> Any:
    """In case the incoming value isn't serialized JSON, reserialize it.

    This lets us use `Json[...]` fields with values that are already deserialized.
    """
    # NOTE: Assumes that the deserialized type is not itself a string.
    # Revisit this if we need to support deserialized types that are str/bytes.
    return v if isinstance(v, (str, bytes)) else to_json(v)


# Allow lenient instantiation/validation: incoming data may already be deserialized.
SerializedToJson = Annotated[
    Json[T], BeforeValidator(ensure_json), PlainSerializer(to_json)
]


class LenientStrEnum(str, Enum):
    """A string enum allowing for case-insensitive lookups by value.

    May include other internal customizations if needed.

    Note: This is a bespoke, internal implementation and NOT intended as a
    backport of `enum.StrEnum` from Python 3.11+.
    """

    def __repr__(self) -> str:
        return self.name

    @classmethod
    def _missing_(cls, value: object) -> Any:
        # Accept case-insensitive enum values
        if isinstance(value, str):
            v = value.lower()
            return next((e for e in cls if e.value.lower() == v), None)
        return None


def default_if_none(v: Any) -> Any:
    """A before-validator validator that coerces `None` to the default field value instead."""
    # https://docs.pydantic.dev/2.11/api/pydantic_core/#pydantic_core.PydanticUseDefault
    if v is None:
        raise PydanticUseDefault
    return v


def upper_if_str(v: Any) -> Any:
    return v.strip().upper() if isinstance(v, str) else v


# ----------------------------------------------------------------------------
def to_scope(v: Any) -> Any:
    """Convert eligible objects, including pre-existing `wandb` types, to an automation scope."""
    from wandb.apis.public import ArtifactCollection, Project

    from .scopes import ProjectScope, _ArtifactPortfolioScope, _ArtifactSequenceScope

    if isinstance(v, Project):
        return ProjectScope(id=v.id, name=v.name)
    if isinstance(v, ArtifactCollection):
        cls = _ArtifactSequenceScope if v.is_sequence() else _ArtifactPortfolioScope
        return cls(id=v.id, name=v.name)
    return v


def to_saved_action(v: Any) -> Any:
    """If necessary (and possible), convert the object to a saved action."""
    from .actions import (
        DoNothing,
        SavedNoOpAction,
        SavedNotificationAction,
        SavedWebhookAction,
        SendNotification,
        SendWebhook,
    )

    if isinstance(v, SendNotification):
        return SavedNotificationAction(
            integration={"id": v.integration_id},
            **v.model_dump(exclude={"integration_id"}),
        )
    if isinstance(v, SendWebhook):
        return SavedWebhookAction(
            integration={"id": v.integration_id},
            **v.model_dump(exclude={"integration_id"}),
        )
    if isinstance(v, DoNothing):
        return SavedNoOpAction.model_validate(v)

    return v


def to_input_action(v: Any) -> Any:
    """If necessary (and possible), convert the object to an input action."""
    from .actions import (
        DoNothing,
        SavedNoOpAction,
        SavedNotificationAction,
        SavedWebhookAction,
        SendNotification,
        SendWebhook,
    )

    if isinstance(v, SavedNotificationAction):
        return SendNotification(
            integration_id=v.integration.id,
            **v.model_dump(exclude={"integration"}),
        )
    if isinstance(v, SavedWebhookAction):
        return SendWebhook(
            integration_id=v.integration.id,
            **v.model_dump(exclude={"integration"}),
        )
    if isinstance(v, SavedNoOpAction):
        return DoNothing.model_validate(v)

    return v


# ----------------------------------------------------------------------------
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
