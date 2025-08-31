"""Events that trigger W&B Automations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Optional, Union

from pydantic import Field
from typing_extensions import Annotated, Self, get_args

from wandb._pydantic import (
    GQLBase,
    field_validator,
    model_validator,
    pydantic_isinstance,
)
from wandb._strutils import nameof

from ._filters import And, MongoLikeFilter, Or
from ._filters.expressions import FilterableField
from ._filters.run_metrics import MetricChangeFilter, MetricThresholdFilter, MetricVal
from ._generated import FilterEventFields
from ._validators import LenientStrEnum, SerializedToJson, ensure_json, simplify_op
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
class _WrappedSavedEventFilter(GQLBase):  # from: TriggeringFilterEvent
    filter: SerializedToJson[MongoLikeFilter] = And()


class _WrappedMetricFilter(GQLBase):  # from: RunMetricFilter
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

    @property
    def event_type(self) -> EventType:
        if self.threshold_filter is not None:
            return EventType.RUN_METRIC_THRESHOLD
        if self.change_filter is not None:
            return EventType.RUN_METRIC_CHANGE
        raise RuntimeError("Expected one of: `threshold_filter` or `change_filter`")


class RunMetricFilter(GQLBase):  # from: TriggeringRunMetricEvent
    run: Annotated[SerializedToJson[MongoLikeFilter], Field(alias="run_filter")] = And()
    metric: Annotated[_WrappedMetricFilter, Field(alias="run_metric_filter")]

    # ------------------------------------------------------------------------------
    legacy_metric_filter: Annotated[
        Optional[SerializedToJson[MetricThresholdFilter]],
        Field(alias="metric_filter", deprecated=True),
    ] = None
    """Deprecated legacy field that was previously used to define run metric threshold events.

    For new automations, use the `metric` field (`run_metric_filter` JSON alias) instead.
    """

    @model_validator(mode="before")
    @classmethod
    def _wrap_metric_filter(cls, v: Any) -> Any:
        if pydantic_isinstance(v, (MetricThresholdFilter, MetricChangeFilter)):
            # If only an (unnested) metric filter is given, nest it under the
            # `metric` field, delegating to inner validator(s) for further
            # wrapping/nesting, if needed.
            # This is necessary to conform to the expected backend schema.
            return cls(metric=v)
        return v

    @field_validator("run", mode="after")
    def _wrap_run_filter(cls, v: MongoLikeFilter) -> Any:
        v_new = simplify_op(v)
        return v_new if pydantic_isinstance(v_new, And) else And(and_=[v_new])


class SavedEvent(FilterEventFields):  # from: FilterEventTriggeringCondition
    """A triggering event from a saved automation."""

    event_type: Annotated[EventType, Field(frozen=True)]  # type: ignore[assignment]

    # We override the type of the `filter` field in order to enforce the expected
    # structure for the JSON data when validating and serializing.
    filter: SerializedToJson[Union[_WrappedSavedEventFilter, RunMetricFilter]]
    """The condition(s) under which this event triggers an automation."""


# ------------------------------------------------------------------------------
# Input types: for creating or updating automations


# Note: The GQL input for "eventFilter" does NOT wrap the filter in an extra `filter` key, unlike the
# eventFilter returned in responses for saved automations.
class _BaseEventInput(GQLBase):
    event_type: EventType

    scope: AutomationScope
    """The scope of the event."""

    filter: SerializedToJson[Any]

    def then(self, action: InputAction) -> NewAutomation:
        """Define a new Automation in which this event triggers the given action."""
        from .automations import NewAutomation

        if isinstance(action, (InputActionTypes, SavedActionTypes)):
            return NewAutomation(event=self, action=action)

        raise TypeError(f"Expected a valid action, got: {nameof(type(action))!r}")

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
    """The scope of the event: only artifact collections are valid scopes for this event."""


# ------------------------------------------------------------------------------
# Events that trigger on run conditions
class _BaseRunEventInput(_BaseEventInput):
    scope: ProjectScope
    """The scope of the event: only projects are valid scopes for this event."""


class OnRunMetric(_BaseRunEventInput):
    """A run metric satisfies a user-defined condition."""

    event_type: Literal[EventType.RUN_METRIC_THRESHOLD, EventType.RUN_METRIC_CHANGE]

    filter: SerializedToJson[RunMetricFilter]
    """Run and/or metric condition(s) that must be satisfied for this event to trigger an automation."""

    @model_validator(mode="before")
    @classmethod
    def _infer_event_type(cls, data: Any) -> Any:
        """Infer the event type at validation time from the inner filter.

        This allows this class to accommodate both "threshold" and "change" metric
        filter types, which are can only be determined after parsing and validating
        the inner JSON data.
        """
        if isinstance(data, dict) and (raw_filter := data.get("filter")):
            # At this point, `raw_filter` may or may not be JSON-serialized
            parsed_filter = RunMetricFilter.model_validate_json(ensure_json(raw_filter))
            return {**data, "event_type": parsed_filter.metric.event_type}

        return data


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
_WrappedSavedEventFilter.model_rebuild()

OnLinkArtifact.model_rebuild()
OnAddArtifactAlias.model_rebuild()
OnCreateArtifact.model_rebuild()
OnRunMetric.model_rebuild()

__all__ = [
    "EventType",
    *(nameof(cls) for cls in InputEventTypes),
    "RunEvent",
    "ArtifactEvent",
    "MetricThresholdFilter",
    "MetricChangeFilter",
]
