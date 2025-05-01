"""Events that trigger W&B Automations."""

# ruff: noqa: UP007  # Avoid using `X | Y` for union fields, as this can cause issues with pydantic < 2.6

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Optional, Union

from pydantic import Field
from typing_extensions import Annotated, Self, get_args

from wandb._pydantic import (
    GQLBase,
    SerializedToJson,
    field_validator,
    model_validator,
    pydantic_isinstance,
)

from ._filters import And, MongoLikeFilter, Or
from ._filters.expressions import FilterableField
from ._filters.run_metrics import MetricChangeFilter, MetricThresholdFilter, MetricVal
from ._generated import FilterEventFields
from ._validators import LenientStrEnum, simplify_op
from .actions import InputAction, InputActionTypes, SavedActionTypes
from .scopes import ArtifactCollectionScope, AutomationScope, ProjectScope

if TYPE_CHECKING:
    from .automations import NewAutomation


# NOTE: Re-defined publicly with a more readable name for easier access
class EventType(LenientStrEnum):
    """The type of event that triggers an automation."""

    # ---------------------------------------------------------------------------
    # Events triggered by GraphQL mutations
    UPDATE_ARTIFACT_ALIAS = "UPDATE_ARTIFACT_ALIAS"  # NOTE: Avoid in new automations

    CREATE_ARTIFACT = "CREATE_ARTIFACT"
    ADD_ARTIFACT_ALIAS = "ADD_ARTIFACT_ALIAS"
    LINK_ARTIFACT = "LINK_MODEL"
    # Note: "LINK_MODEL" is the (legacy) value expected by the backend, but we
    # name it "LINK_ARTIFACT" here in the public API for clarity and consistency.

    # ---------------------------------------------------------------------------
    # Events triggered by Run conditions
    RUN_METRIC_THRESHOLD = "RUN_METRIC"
    RUN_METRIC_CHANGE = "RUN_METRIC_CHANGE"


# ------------------------------------------------------------------------------
# Saved types: for parsing response data from saved automations


# Note: In GQL responses containing saved automation data, the filter is wrapped in an extra `filter` key.
class SavedEventFilter(GQLBase):  # in wandb/core: `TriggeringFilterEvent`
    filter: SerializedToJson[MongoLikeFilter] = Field(default_factory=And)


class _WrappedMetricFilter(GQLBase):  # in wandb/core: `RunMetricFilter`
    threshold_filter: Optional[MetricThresholdFilter] = None
    change_filter: Optional[MetricChangeFilter] = None

    @model_validator(mode="before")
    @classmethod
    def _wrap_metric_filter(cls, v: Any) -> Any:
        if pydantic_isinstance(v, MetricThresholdFilter):
            return cls(threshold_filter=v)
        if pydantic_isinstance(v, MetricChangeFilter):
            return cls(change_filter=v)
        return v

    @model_validator(mode="after")
    def _ensure_exactly_one_set(self) -> Self:
        set_fields = [name for name, val in self if (val is not None)]

        if not set_fields:
            all_names = ", ".join(map(repr, type(self).model_fields))
            raise ValueError(f"Expected one of: {all_names}")

        if len(set_fields) > 1:
            set_names = ", ".join(map(repr, set_fields))
            raise ValueError(f"Expected exactly one metric filter, got: {set_names}")

        return self


class RunMetricFilter(GQLBase):  # in wandb/core: `TriggeringRunMetricEvent`
    run: Annotated[SerializedToJson[MongoLikeFilter], Field(alias="run_filter")] = And()
    metric: Annotated[_WrappedMetricFilter, Field(alias="run_metric_filter")]

    #: Legacy field to define triggers on run metrics from absolute thresholds.  For new automations, use `run_metric_filter` instead.
    metric_filter: Optional[SerializedToJson[MetricThresholdFilter]] = Field(
        default=None,
        deprecated="The `metric_filter` field is deprecated: use `metric/run_metric_filter` instead.",
    )

    @model_validator(mode="before")
    @classmethod
    def _wrap_metric_filter(cls, v: Any) -> Any:
        if pydantic_isinstance(v, MetricThresholdFilter):
            # If we're only given an (unwrapped) metric filter, automatically wrap/nest it
            # following the structure expected by the backend.  Delegate to inner validator(s)
            # for additional wrapping, if needed.
            return cls(metric=v)
        return v

    @field_validator("run", mode="after")
    def _wrap_run_filter(cls, v: MongoLikeFilter) -> Any:
        v_new = simplify_op(v)
        return v_new if pydantic_isinstance(v_new, And) else And(and_=[v_new])


class SavedEvent(FilterEventFields):  # from `FilterEventTriggeringCondition`
    """A triggering event from a saved automation."""

    event_type: Annotated[EventType, Field(frozen=True)]  # type: ignore[assignment]

    # We override the type of the `filter` field to enforce more specific
    # expectations for the structure of the JSON data (and parse/serialize
    # accordingly).
    filter: SerializedToJson[Union[SavedEventFilter, RunMetricFilter]]
    """The condition(s) under which this event triggers an automation."""


# ------------------------------------------------------------------------------
# Input types: for creating or updating automations


# Note: The GQL input for "eventFilter" does NOT wrap the filter in an extra `filter` key, unlike the
# eventFilter returned in responses for saved automations.
class _BaseEventInput(GQLBase):
    event_type: Annotated[EventType, Field(frozen=True)]

    scope: AutomationScope
    """The scope of the event."""

    filter: SerializedToJson[Any]

    def then(self, action: InputAction) -> NewAutomation:
        """Define a new Automation in which this event triggers the given action."""
        from .automations import NewAutomation

        if isinstance(action, (InputActionTypes, SavedActionTypes)):
            return NewAutomation(event=self, action=action)

        raise TypeError(f"Expected a valid action, got: {type(action).__qualname__!r}")

    def __rshift__(self, other: InputAction) -> NewAutomation:
        """Implements `event >> action` to define an Automation with this event and action."""
        return self.then(other)


# ------------------------------------------------------------------------------
# Events that trigger on specific mutations in the backend
class _BaseMutationEventInput(_BaseEventInput):
    filter: SerializedToJson[MongoLikeFilter] = And()
    """Additional condition(s), if any, that must be met for this event to trigger an automation."""

    @field_validator("filter", mode="after")
    def _wrap_filter(cls, v: Any) -> Any:
        """Ensure the given filter is wrapped like: `{"$or": [{"$and": [<original_filter>]}]}`.

        This is awkward but necessary, because the frontend expects this format.
        """
        v_new = simplify_op(v)
        v_new = v_new if pydantic_isinstance(v_new, And) else And(and_=[v_new])
        return Or(or_=[v_new])


class OnLinkArtifact(_BaseMutationEventInput):
    """A new artifact is linked to a collection."""

    event_type: Literal[EventType.LINK_ARTIFACT] = EventType.LINK_ARTIFACT


class OnAddArtifactAlias(_BaseMutationEventInput):
    """A new alias is assigned to an artifact."""

    event_type: Literal[EventType.ADD_ARTIFACT_ALIAS] = EventType.ADD_ARTIFACT_ALIAS


class OnCreateArtifact(_BaseMutationEventInput):
    """A new artifact is created."""

    event_type: Literal[EventType.CREATE_ARTIFACT] = EventType.CREATE_ARTIFACT

    scope: ArtifactCollectionScope
    """The scope of the event.

    Note: only collection scopes are supported for this event.
    """


# ------------------------------------------------------------------------------
# Events that trigger on run conditions
class _BaseRunEventInput(_BaseEventInput):
    scope: ProjectScope
    """The scope of the event.

    Note: only project scopes are supported for this event.
    """


class OnRunMetric(_BaseRunEventInput):
    """A run metric satisfies a user-defined condition."""

    event_type: Literal[EventType.RUN_METRIC_THRESHOLD] = EventType.RUN_METRIC_THRESHOLD

    filter: SerializedToJson[RunMetricFilter]
    """Run and/or metric condition(s) that must be satisfied for this event to trigger an automation."""


# for type annotations
InputEvent = Annotated[
    Union[
        OnLinkArtifact,
        OnAddArtifactAlias,
        OnCreateArtifact,
        OnRunMetric,
    ],
    Field(discriminator="event_type"),
]
# for runtime type checks
InputEventTypes: tuple[type, ...] = get_args(InputEvent.__origin__)  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------


class RunEvent:
    name = FilterableField(server_name="display_name")
    # `Run.name` is actually filtered on `Run.display_name` in the backend.
    # We can't reasonably expect users to know this a priori, so
    # automatically fix it here.

    @staticmethod
    def metric(name: str) -> MetricVal:
        """Define a metric filter condition."""
        return MetricVal(name=name)


class ArtifactEvent:
    alias = FilterableField()


MetricThresholdFilter.model_rebuild()
RunMetricFilter.model_rebuild()
SavedEventFilter.model_rebuild()

OnLinkArtifact.model_rebuild()
OnAddArtifactAlias.model_rebuild()
OnCreateArtifact.model_rebuild()
OnRunMetric.model_rebuild()

__all__ = [
    "EventType",
    *(cls.__name__ for cls in InputEventTypes),
    "RunEvent",
    "ArtifactEvent",
]
