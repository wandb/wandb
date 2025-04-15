"""Events that trigger W&B Automations."""

# ruff: noqa: UP007  # Avoid using `X | Y` for union fields, as this can cause issues with pydantic < 2.6

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Optional, Union

from pydantic import Field
from typing_extensions import Self, TypeAlias, get_args

from wandb._pydantic import (
    GQLBase,
    SerializedToJson,
    field_validator,
    model_validator,
    pydantic_isinstance,
)

from ._filters import And, MongoLikeFilter, Or
from ._filters.expressions import FilterableField
from ._filters.run_metrics import (
    Agg,
    MetricChangeFilter,
    MetricOperand,
    MetricThresholdFilter,
)
from ._generated import EventTriggeringConditionType, FilterEventFields
from ._validators import simplify_op
from .actions import InputAction, InputActionTypes
from .scopes import ArtifactCollectionScope, InputScope, ProjectScope

if TYPE_CHECKING:
    from .automations import NewAutomation


# NOTE: Re-defined publicly with a more readable name for easier access
EventType = EventTriggeringConditionType
"""The type of event that triggers an automation."""

Agg = Agg


# ------------------------------------------------------------------------------
# Saved types: for parsing response data from saved automations


# Note: In GQL responses containing saved automation data, the filter is wrapped in an extra `filter` key.
class SavedEventFilter(GQLBase):
    filter: SerializedToJson[MongoLikeFilter] = Field(default_factory=And)


class _InnerRunMetricFilter(GQLBase):  # from `RunMetricFilter`
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
        set_field_names = [name for name, val in self if (val is not None)]
        if not set_field_names:
            raise ValueError("Must specify a run metric filter")
        if len(set_field_names) > 1:
            names = ", ".join(map(repr, set_field_names))
            raise ValueError(f"Must specify a single run metric filter, got: {names}")
        return self


class RunMetricFilter(GQLBase):  # from `RunMetricEvent`
    run_filter: SerializedToJson[MongoLikeFilter] = Field(default_factory=And)
    run_metric_filter: _InnerRunMetricFilter

    #: Legacy field to define triggers on run metrics from absolute thresholds.  Use `run_metric_filter` instead.
    metric_filter: Optional[SerializedToJson[MetricThresholdFilter]] = Field(
        default=None,
        deprecated="The `metric_filter` field is deprecated: use `run_metric_filter` instead.",
    )

    @model_validator(mode="before")
    @classmethod
    def _wrap_metric_filter(cls, v: Any) -> Any:
        if pydantic_isinstance(v, (MetricThresholdFilter, MetricChangeFilter)):
            # If we're only given an (unwrapped) metric filter, automatically wrap it
            # in the appropriate nested structure, and use the default run filter.

            # Delegate to the inner validator to further wrap the filter as appropriate.
            return cls(run_metric_filter=_InnerRunMetricFilter.model_validate(v))
        return v

    @field_validator("run_filter", mode="after")
    @classmethod
    def _wrap_run_filter(cls, v: MongoLikeFilter) -> Any:
        v_new = simplify_op(v)
        return (
            And.model_validate(v_new)
            if pydantic_isinstance(v_new, And)
            else And(and_=[v_new])
        )


# type alias defined for naming consistency/clarity
SavedRunMetricFilter: TypeAlias = RunMetricFilter


class SavedEvent(FilterEventFields):  # from `FilterEventTriggeringCondition`
    """A more introspection-friendly representation of a triggering event from a saved automation."""

    # We override the type of the `filter` field since the original GraphQL
    # schema (and generated class) defines it as a JSONString (str), but we
    # have more specific expectations for the structure of the JSON data.
    filter: SerializedToJson[Union[SavedEventFilter, SavedRunMetricFilter]]


# ------------------------------------------------------------------------------
# Input types: for creating or updating automations


# Note: The GQL input for "eventFilter" does NOT wrap the filter in an extra `filter` key, unlike the
# eventFilter returned in responses for saved automations.
class _BaseEventInput(GQLBase):
    event_type: EventType
    scope: InputScope
    filter: SerializedToJson[Any]

    def add_action(self, action: InputAction) -> NewAutomation:
        """Define an executed action to be triggered by this event."""
        from .automations import NewAutomation

        if isinstance(action, InputActionTypes):
            return NewAutomation(scope=self.scope, event=self, action=action)

        raise TypeError(f"Expected a valid action, got: {type(action).__qualname__!r}")

    def __rshift__(self, other: InputAction) -> NewAutomation:
        """Supports `event >> action` as syntactic sugar to combine an event and action."""
        return self.add_action(other)


class _BaseMutationEventInput(_BaseEventInput):
    event_type: EventType
    scope: InputScope
    filter: SerializedToJson[MongoLikeFilter] = Field(default_factory=And)

    @field_validator("filter", mode="after")
    @classmethod
    def _wrap_filter(cls, v: Any) -> Any:
        """Ensure the given filter is wrapped like: `{"$or": [{"$and": [<original_filter>]}]}`.

        This is awkward but necessary, because the frontend expects this format.
        """
        v_new = simplify_op(v)
        v_new = (
            And.model_validate(v_new)
            if pydantic_isinstance(v_new, And)
            else And(and_=[v_new])
        )
        v_new = Or(or_=[v_new])
        return v_new


class OnLinkArtifact(_BaseMutationEventInput):
    """A new artifact is linked to a collection."""

    event_type: Literal[EventType.LINK_MODEL] = EventType.LINK_MODEL
    scope: InputScope


class OnAddArtifactAlias(_BaseMutationEventInput):
    """A new alias is assigned to an artifact."""

    event_type: Literal[EventType.ADD_ARTIFACT_ALIAS] = EventType.ADD_ARTIFACT_ALIAS
    scope: InputScope


class OnCreateArtifact(_BaseMutationEventInput):
    """A new artifact is created."""

    event_type: Literal[EventType.CREATE_ARTIFACT] = EventType.CREATE_ARTIFACT
    scope: ArtifactCollectionScope


class OnRunMetric(_BaseEventInput):
    """A run metric satisfies a user-defined absolute threshold."""

    event_type: Literal[EventType.RUN_METRIC] = EventType.RUN_METRIC
    scope: ProjectScope
    filter: SerializedToJson[RunMetricFilter]


# for type annotations
InputEvent = Union[
    OnLinkArtifact,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnRunMetric,
]
# for runtime type checks
InputEventTypes: tuple[type, ...] = get_args(InputEvent)


# ----------------------------------------------------------------------------


class RunEvent:
    name = FilterableField("display_name")
    # `Run.name` is actually filtered on `Run.display_name` in the backend.
    # We can't reasonably expect users to know this a priori, so
    # automatically fix it here.

    @staticmethod
    def metric(name: str) -> MetricOperand:
        """Define a metric filter condition."""
        return MetricOperand(name=name)


class ArtifactEvent:
    alias = FilterableField()


MetricThresholdFilter.model_rebuild()
RunMetricFilter.model_rebuild()
SavedEventFilter.model_rebuild()

OnLinkArtifact.model_rebuild()
OnAddArtifactAlias.model_rebuild()
OnCreateArtifact.model_rebuild()
OnRunMetric.model_rebuild()
