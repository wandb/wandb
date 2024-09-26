"""Events that trigger W&B Automations."""

from __future__ import annotations

from abc import ABC
from enum import Enum
from functools import cache
from typing import TYPE_CHECKING, Any, Literal, NoReturn, TypeAlias, TypeVar

from pydantic import ConfigDict, Field, Json, PositiveInt, field_validator
from pydantic._internal import _repr
from typing_extensions import override

from wandb.sdk.automations._base import Base
from wandb.sdk.automations._generated.enums import EventTriggeringConditionType
from wandb.sdk.automations._ops.funcs import and_, on_field
from wandb.sdk.automations._ops.logic import And
from wandb.sdk.automations._ops.op import AnyExpr, FieldFilter
from wandb.sdk.automations._typing import Typename
from wandb.sdk.automations._utils import jsonify
from wandb.sdk.automations.actions import NewNotification, NewQueueJob, NewWebhook
from wandb.sdk.automations.automations import AnyNewAction
from wandb.sdk.automations.scopes import ArtifactCollection, Project

if TYPE_CHECKING:
    from typing_extensions import Self


# FIXME: Find a way to autogenerate this too
class Aggregation(str, Enum):
    MAX = "MAX"
    MIN = "MIN"
    AVERAGE = "AVERAGE"


@cache
def _empty_json_filter() -> Json[And]:
    return jsonify(and_())


@cache
def _empty_json_event_filter() -> Json[EventFilter]:
    return jsonify(EventFilter(filter=_empty_json_filter()))


class EventFilter(Base):
    filter: Json[AnyExpr] | Json[dict[str, Any]]  # | Literal[""]


class RunMetricFilter(Base):
    model_config = ConfigDict(alias_generator=None)

    run_filter: Json[RunFilter] = _empty_json_filter()
    metric_filter: Json[MetricThresholdFilter]

    @field_validator("metric_filter", mode="before")
    @classmethod
    def _jsonify_metric_filter(
        cls, v: MetricThresholdFilter | dict[str, Any] | str
    ) -> str:
        if isinstance(v, (MetricThresholdFilter, dict)):
            return jsonify(MetricThresholdFilter.model_validate(v))  # type: ignore[arg-type]  # FIXME
        return v

    @field_validator("run_filter", mode="before")
    @classmethod
    def _jsonify_filter(cls, v: RunFilter | dict[str, Any] | str) -> str:
        if isinstance(v, (RunFilter, dict)):
            return jsonify(RunFilter.model_validate(v))  # type: ignore[arg-type]  # FIXME
        return v

    def __repr_args__(self) -> _repr.ReprArgs:
        for name, _ in self.model_fields.items():
            if name in self.model_fields_set:
                yield name, getattr(self, name)


class RunFilter(And):
    @override
    def __and__(self, other: MetricThresholdFilter) -> RunMetricFilter:
        if isinstance(other, MetricThresholdFilter):
            return RunMetricFilter(
                run_filter=self,
                metric_filter=other,
            )
        raise NotImplementedError


class MetricThresholdFilter(Base):
    model_config = ConfigDict(alias_generator=None)

    name: str
    window_size: PositiveInt = 1
    agg_op: Aggregation | None = None
    cmp_op: str
    threshold: int | float

    def __and__(self, other: RunFilter) -> RunMetricFilter:
        if isinstance(other, RunFilter):
            return RunMetricFilter(
                run_filter=other,
                metric_filter=self,
            )
        raise NotImplementedError


class Event(Base):
    """A more introspection-friendly representation of a triggering event from a saved automation."""

    typename__: Typename[Literal["FilterEventTriggeringCondition"]]
    event_type: EventTriggeringConditionType
    filter: Json[EventFilter] | Json[RunMetricFilter]

    def __repr_name__(self) -> str:  # type: ignore[override]
        return str(self.event_type)


class NewEvent(Base, ABC):
    event_type: EventTriggeringConditionType
    scope: ArtifactCollection | Project
    filter: Json[EventFilter | RunMetricFilter]

    # TODO: Deprecate this
    def triggers_action(self, action: AnyNewAction) -> NewEventAndAction:
        if isinstance(action, (NewQueueJob, NewNotification, NewWebhook)):
            return self, action
        raise TypeError(
            f"Expected an instance of a new action type, got: {type(action).__qualname__!r}"
        )

    def __rshift__(self, other: AnyNewAction) -> NewEventAndAction:
        """Connect this event to an action using, e.g. `event >> action`."""
        return self.triggers_action(other)

    def __gt__(self, other: AnyNewAction) -> NoReturn:
        """Let's not get ahead of ourselves here -- don't overload the comparison operators as well."""
        raise RuntimeError("Did you mean to use the '>>' operator?")


NewEventT = TypeVar("NewEventT", bound=NewEvent)
NewActionT = TypeVar("NewActionT", bound=AnyNewAction)
NewEventAndAction: TypeAlias = tuple[NewEventT, NewActionT]


class NewLinkArtifact(NewEvent):
    """A new artifact is linked to a collection."""

    event_type: Literal[EventTriggeringConditionType.LINK_MODEL] = Field(
        EventTriggeringConditionType.LINK_MODEL, init=False
    )

    scope: ArtifactCollection | Project
    filter: Json[EventFilter] = Field(default_factory=_empty_json_event_filter)


class NewAddArtifactAlias(NewEvent):
    """A new alias is assigned to an artifact."""

    event_type: Literal[EventTriggeringConditionType.ADD_ARTIFACT_ALIAS] = Field(
        EventTriggeringConditionType.ADD_ARTIFACT_ALIAS, init=False
    )

    scope: ArtifactCollection | Project
    filter: Json[EventFilter]

    @classmethod
    def from_pattern(cls, alias: str, **kwargs: Any) -> Self:
        return cls(
            **kwargs,
            filter=jsonify(
                EventFilter(
                    filter=jsonify(on_field("alias").regex_match(alias)),
                ),
            ),
        )


class NewCreateArtifact(NewEvent):
    """A new artifact is created."""

    event_type: Literal[EventTriggeringConditionType.CREATE_ARTIFACT] = Field(
        EventTriggeringConditionType.CREATE_ARTIFACT, init=False
    )

    scope: ArtifactCollection | Project
    filter: Json[EventFilter] = Field(default_factory=_empty_json_event_filter)


class NewRunMetric(NewEvent):
    event_type: Literal[EventTriggeringConditionType.RUN_METRIC] = Field(
        EventTriggeringConditionType.RUN_METRIC, init=False
    )

    scope: Project
    filter: Json[RunMetricFilter]

    @field_validator("filter", mode="before")
    @classmethod
    def _jsonify_filter(cls, v: Any) -> Any:
        if isinstance(v, RunMetricFilter):
            return jsonify(v)
        if isinstance(v, MetricThresholdFilter):
            # If we're only given a metric threshold condition, assume we trigger on "all runs" in scope
            return jsonify(RunMetricFilter(metric_filter=v))
        return v


# ------------------------------------------------------------------------------
# TODO: Move this, make more generic, and refactor with proper descriptor types
class _RunNameMatchable:
    @staticmethod
    def contains(text: str) -> RunFilter:
        field_name = "display_name"
        return RunFilter.model_validate(
            And(
                exprs=[
                    FieldFilter.model_validate({field_name: {"$contains": text}}),
                ],
            )
        )


class _ListMatchable:
    def contains(self, text: str) -> Self:
        raise NotImplementedError


class _MetricMatchable:
    name: str
    agg_op: Aggregation | None
    window_size: int

    def __init__(self, name: str):
        self.name = name
        self.agg_op = None
        self.window_size = 1

    def average(self, window: int) -> Self:
        self.agg_op = Aggregation.AVERAGE
        self.window_size = window
        return self

    def max(self, window: int) -> Self:
        self.agg_op = Aggregation.MAX
        self.window_size = window
        return self

    def min(self, window: int) -> Self:
        self.agg_op = Aggregation.MIN
        self.window_size = window
        return self

    def __gt__(self, other: int | float) -> MetricThresholdFilter:
        return MetricThresholdFilter(
            name=self.name,
            agg_op=self.agg_op,
            window_size=self.window_size,
            threshold=other,
            cmp_op="$gt",
        )

    def __lt__(self, other: int | float) -> MetricThresholdFilter:
        return MetricThresholdFilter(
            name=self.name,
            agg_op=self.agg_op,
            window_size=self.window_size,
            threshold=other,
            cmp_op="$lt",
        )

    def __ge__(self, other: int | float) -> MetricThresholdFilter:
        return MetricThresholdFilter(
            name=self.name,
            agg_op=self.agg_op,
            window_size=self.window_size,
            threshold=other,
            cmp_op="$gte",
        )

    def __le__(self, other: int | float) -> MetricThresholdFilter:
        return MetricThresholdFilter(
            name=self.name,
            agg_op=self.agg_op,
            window_size=self.window_size,
            threshold=other,
            cmp_op="$lte",
        )


class Run:
    name = _RunNameMatchable()

    @staticmethod
    def metric(name: str) -> _MetricMatchable:
        return _MetricMatchable(name=name)
