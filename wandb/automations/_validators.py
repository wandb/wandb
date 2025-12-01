from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar

from pydantic import BeforeValidator, Json, PlainSerializer
from pydantic_core import PydanticUseDefault
from typing_extensions import Annotated

from wandb._pydantic import to_json

from ._filters import And, MongoLikeFilter, Or
from ._filters.filterutils import simplify_expr

T = TypeVar("T")


def ensure_json(v: Any) -> Any:
    """In case the incoming value isn't serialized JSON, reserialize it.

    This lets us use `Json[...]` fields with values that are already deserialized.
    """
    # NOTE: Assumes that the deserialized type is not itself a string.
    # Revisit this if we need to support deserialized types that are str/bytes.
    return v if isinstance(v, (str, bytes)) else to_json(v)


JsonEncoded = Annotated[Json[T], BeforeValidator(ensure_json), PlainSerializer(to_json)]
"""A Pydantic type that's always serialized to a JSON string.

Unlike `pydantic.Json[T]`, this is more lenient on validation and instantiation.
It doesn't strictly require the incoming value to be an encoded JSON string, and
accepts values that may _already_ be deserialized from JSON (e.g. a dict).
"""


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
    """A "before"-mode field validator that coerces `None` to the field default.

    See: https://docs.pydantic.dev/2.11/api/pydantic_core/#pydantic_core.PydanticUseDefault
    """
    if v is None:
        raise PydanticUseDefault
    return v


def upper_if_str(v: Any) -> Any:
    return v.strip().upper() if isinstance(v, str) else v


# ----------------------------------------------------------------------------
def parse_scope(v: Any) -> Any:
    """Convert eligible objects (including wandb types) to an automation scope."""
    from wandb.apis.public import ArtifactCollection, Project

    from .scopes import ProjectScope, _ArtifactPortfolioScope, _ArtifactSequenceScope

    if isinstance(v, Project):
        return ProjectScope.model_validate(v)
    if isinstance(v, ArtifactCollection):
        typ = _ArtifactSequenceScope if v.is_sequence() else _ArtifactPortfolioScope
        return typ.model_validate(v)
    return v


def parse_saved_action(v: Any) -> Any:
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
            integration={"id": v.integration_id}, **v.model_dump()
        )
    if isinstance(v, SendWebhook):
        return SavedWebhookAction(
            integration={"id": v.integration_id}, **v.model_dump()
        )
    if isinstance(v, DoNothing):
        return SavedNoOpAction(**v.model_dump())
    return v


def parse_input_action(v: Any) -> Any:
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
        return SendNotification(integration_id=v.integration.id, **v.model_dump())
    if isinstance(v, SavedWebhookAction):
        return SendWebhook(integration_id=v.integration.id, **v.model_dump())
    if isinstance(v, SavedNoOpAction):
        return DoNothing(**v.model_dump())
    return v


# ----------------------------------------------------------------------------
def wrap_run_event_run_filter(f: MongoLikeFilter) -> MongoLikeFilter:
    """Wrap a run filter in an `And` operator if it's not already.

    This is a necessary constraint imposed elsewhere by backend/frontend code.
    """
    return And.wrap(simplify_expr(f))  # simplify/flatten first if needed


def wrap_mutation_event_filter(f: MongoLikeFilter) -> MongoLikeFilter:
    """Wrap filters as `{"$or": [{"$and": [<original_filter>]}]}`.

    This awkward format is necessary because the frontend expects it.
    """
    return Or.wrap(And.wrap(simplify_expr(f)))  # simplify/flatten first if needed
