from __future__ import annotations

from enum import StrEnum, global_enum
from typing import Literal, Union

from pydantic import ConfigDict, Field, Json
from typing_extensions import Annotated

from wandb.apis.public import ArtifactCollection, Project
from wandb.sdk.automations._typing import TypenameField
from wandb.sdk.automations.actions import ActionInput
from wandb.sdk.automations.base import Base
from wandb.sdk.automations.expr import And, AnyExpr, Or, QueryExpr

# Triggers on GraphQL mutations


# Legacy names
@global_enum
class FilterEventType(StrEnum):
    ADD_ARTIFACT_ALIAS = "ADD_ARTIFACT_ALIAS"
    CREATE_ARTIFACT = "CREATE_ARTIFACT"
    LINK_ARTIFACT = "LINK_MODEL"
    UPDATE_ARTIFACT_ALIAS = "UPDATE_ARTIFACT_ALIAS"


ADD_ARTIFACT_ALIAS = FilterEventType.ADD_ARTIFACT_ALIAS
CREATE_ARTIFACT = FilterEventType.CREATE_ARTIFACT
LINK_ARTIFACT = FilterEventType.LINK_ARTIFACT
UPDATE_ARTIFACT_ALIAS = FilterEventType.UPDATE_ARTIFACT_ALIAS


class Filter(Base):
    filter: Json[AnyExpr]


class FilterEvent(Base):
    typename__: TypenameField[Literal["FilterEventTriggeringCondition"]]
    event_type: FilterEventType
    filter: Json[Filter]


# ------------------------------------------------------------------------------
# Legacy
class EventInput(Base):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    scope: ArtifactCollection | Project
    event_type: FilterEventType
    filter: Json[Filter]

    def __rshift__(self, other: ActionInput) -> tuple[EventInput, ActionInput]:
        if isinstance(other, ActionInput):
            return self, other
        raise TypeError(f"Target of >> should be an {ActionInput.__name__!r} object")


class LinkArtifactInput(EventInput):
    scope: ArtifactCollection

    event_type: Literal[FilterEventType.LINK_ARTIFACT] = Field(
        default=LINK_ARTIFACT, init=False, frozen=True
    )
    filter: Json[Filter] = Field(
        default=Filter(
            filter=Or(exprs=[And(exprs=[])]).model_dump_json()
        ).model_dump_json(),
        init=False,
        frozen=True,
    )


# ------------------------------------------------------------------------------
# TODO: This is a WIP Triggers on run metrics
class RunMetricEvent(Base):
    typename__: TypenameField[Literal["RunMetricTriggeringCondition"]]
    event_type: str  # TODO: TBD

    run_filter: Json[Filter]
    metric_filter: Json[QueryExpr]


AnyEvent = Annotated[
    Union[
        FilterEvent,
        RunMetricEvent,
    ],
    Field(alias="triggeringCondition"),
]
