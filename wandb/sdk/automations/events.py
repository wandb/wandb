from __future__ import annotations

from enum import StrEnum, global_enum
from typing import Any, Literal, NoReturn, TypeAlias, Union

from pydantic import Field, Json
from pydantic._internal import _repr
from typing_extensions import Annotated, Final, Self

from wandb.sdk.automations._typing import Typename
from wandb.sdk.automations._utils import jsonify
from wandb.sdk.automations.actions import NewAction
from wandb.sdk.automations.base import Base
from wandb.sdk.automations.operators.logic import And, Or
from wandb.sdk.automations.operators.op import (
    AnyExpr,
    AnyOp,
    FieldFilter,
    and_,
    on_field,
    or_,
)
from wandb.sdk.automations.scopes import ArtifactCollectionScope, ProjectScope


# Legacy names
@global_enum
class EventType(StrEnum):
    ADD_ARTIFACT_ALIAS = "ADD_ARTIFACT_ALIAS"
    CREATE_ARTIFACT = "CREATE_ARTIFACT"
    LINK_ARTIFACT = "LINK_MODEL"
    UPDATE_ARTIFACT_ALIAS = "UPDATE_ARTIFACT_ALIAS"


ADD_ARTIFACT_ALIAS = EventType.ADD_ARTIFACT_ALIAS
CREATE_ARTIFACT = EventType.CREATE_ARTIFACT
LINK_ARTIFACT = EventType.LINK_ARTIFACT
UPDATE_ARTIFACT_ALIAS = EventType.UPDATE_ARTIFACT_ALIAS


class EventFilter(Base):
    filter: Json[AnyExpr] | Json[dict[str, Any]]


class Event(Base):
    typename__: Typename[Literal["FilterEventTriggeringCondition"]]
    event_type: EventType
    filter: Json[EventFilter]

    def __repr_name__(self) -> str:
        return str(self.event_type)

    def __repr_args__(self) -> _repr.ReprArgs:
        inner_expr = self.filter.filter
        while isinstance(inner_expr, (Or, And)) and len(inner_expr.exprs) <= 1:
            if not inner_expr.exprs:
                inner_expr = None
                break
            else:
                inner_expr = inner_expr.exprs[0]
        yield "filter", inner_expr


# TODO: This is a WIP Triggers on run metrics
class RunMetricEvent(Base):
    typename__: Typename[Literal["RunMetricTriggeringCondition"]]
    event_type: str  # TODO: TBD

    run_filter: Json[EventFilter]
    metric_filter: Json[FieldFilter]


class EventTrigger(Base):
    event_type: EventType
    # scope: ArtifactCollection | Project
    scope: ArtifactCollectionScope | ProjectScope
    filter: Json[EventFilter]

    # TODO: Deprecate this
    def link_action(self, action: NewAction) -> NewEventAndAction:
        if isinstance(action, NewAction):
            return self, action
        raise TypeError(
            f"Expected an instance of {NewAction.__name__!r}, got: {type(action).__qualname__!r}"
        )

    def __rshift__(self, other: NewAction) -> NewEventAndAction:
        """Connect this event to an action using, e.g. `event >> action`."""
        return self.link_action(other)

    def __gt__(self, other: NewAction) -> NoReturn:
        """Let's not get too ahead of ourselves here, no overloading the comparison operators."""
        raise RuntimeError("Did you mean to use the '>>' operator?")


NewEventAndAction: TypeAlias = tuple[EventTrigger, NewAction]

_DEFAULT_EMPTY_FILTER: Final[str] = jsonify(EventFilter(filter=jsonify(or_(and_()))))


class LinkArtifact(EventTrigger):
    """A new artifact is linked to a collection."""

    event_type: Literal[EventType.LINK_ARTIFACT] = LINK_ARTIFACT

    scope: ArtifactCollectionScope | ProjectScope
    filter: Json[EventFilter] = Field(default_factory=lambda: _DEFAULT_EMPTY_FILTER)


class AddArtifactAlias(EventTrigger):
    """A new alias is assigned to an artifact."""

    event_type: Literal[EventType.ADD_ARTIFACT_ALIAS] = ADD_ARTIFACT_ALIAS

    scope: ArtifactCollectionScope | ProjectScope
    filter: Json[EventFilter]

    @classmethod
    def from_pattern(cls, alias: str, **kwargs: Any) -> Self:
        return cls(
            **kwargs,
            filter=jsonify(
                EventFilter(filter=jsonify(on_field("alias").regex_match(alias))),
            ),
        )


class CreateArtifact(EventTrigger):
    """A new artifact is created."""

    event_type: Literal[EventType.CREATE_ARTIFACT] = CREATE_ARTIFACT

    scope: ArtifactCollectionScope | ProjectScope
    filter: Json[EventFilter] = _DEFAULT_EMPTY_FILTER


# ------------------------------------------------------------------------------


AnyEvent = Annotated[
    Union[
        Event,
        # RunMetricEvent,
    ],
    Field(alias="triggeringCondition"),
]


AnyNewEvent = Annotated[
    Union[LinkArtifact | AddArtifactAlias, CreateArtifact],
    Field(discriminator="event_type"),
]
