"""Events that trigger W&B Automations."""

from __future__ import annotations

import sys
from enum import Enum
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import ConfigDict, Field, Json, PositiveInt, field_validator
from pydantic._internal import _repr

from wandb.sdk.automations._base import Base
from wandb.sdk.automations._filters.filter import AnyExpr, FilterExpression
from wandb.sdk.automations._filters.funcs import on_field
from wandb.sdk.automations._filters.logic import And
from wandb.sdk.automations._generated.enums import EventTriggeringConditionType
from wandb.sdk.automations._utils import SerializedToJson, jsonify
from wandb.sdk.automations.actions import DoLaunchJob, DoNotification, DoWebhook
from wandb.sdk.automations.scopes import ArtifactCollection, Project

if TYPE_CHECKING:
    from wandb.sdk.automations.automations import (
        ActionInputT,
        EventAndActionInput,
        EventInputT,
    )

if sys.version_info >= (3, 12):
    from typing import Self, override
else:
    from typing_extensions import Self, override


# TODO: Find a way to autogenerate this too
class Aggregation(str, Enum):
    MAX = "MAX"
    MIN = "MIN"
    AVERAGE = "AVERAGE"


class EventFilter(Base):
    filter: SerializedToJson[AnyExpr | dict[str, Any]] = Field(default_factory=And)


class RunFilter(And):
    @override
    def __and__(self, other: MetricFilter) -> RunMetricFilter:  # type: ignore[override]
        if isinstance(other, MetricFilter):
            return RunMetricFilter(run_filter=self, metric_filter=other)
        raise NotImplementedError


class MetricFilter(Base):
    model_config = ConfigDict(alias_generator=None)  # JSON fields here are snake_case

    name: str
    window_size: PositiveInt = Field(
        default=1,
        le=10,  # NOTE: For now, enforce maximum window size of 10 here
    )
    agg_op: Aggregation | None = None
    cmp_op: Literal["$gte", "$gt", "$lt", "$lte"]
    threshold: int | float

    def __and__(self, other: RunFilter) -> RunMetricFilter:
        if isinstance(other, RunFilter):
            return RunMetricFilter(run_filter=other, metric_filter=self)
        raise NotImplementedError

    _OP_MAP: Final[dict[str, str]] = {
        "$gte": ">=",
        "$gt": ">",
        "$lte": "<=",
        "$lt": "<",
    }

    def __repr__(self) -> str:
        cls_name = type(self).__qualname__

        metric = f"`{self.name}`"

        left = f"{agg.value.lower()}({metric})" if (agg := self.agg_op) else metric
        op = self._OP_MAP[self.cmp_op]
        right = f"{self.threshold}"

        expr = f"{left} {op} {right}"

        return f"{cls_name}({expr!r})"


class OnEvent(Base):
    event_type: EventTriggeringConditionType
    scope: ArtifactCollection | Project
    filter: Json[EventFilter | RunMetricFilter]

    # # TODO: Deprecate this
    # def triggers(
    #     self, action: ActionInputT
    # ) -> EventAndActionInput[EventInputT, ActionInputT]:
    #     if isinstance(action, (DoLaunchJob, DoNotification, DoWebhook)):
    #         return self, action
    #     raise TypeError(
    #         f"Expected an instance of a new action type, got: {type(action).__qualname__!r}"
    #     )

    def __rshift__(
        self, other: ActionInputT
    ) -> EventAndActionInput[EventInputT, ActionInputT]:
        """Supports syntactic sugar to define the action triggered by this event as: `event >> action`."""
        if isinstance(other, (DoLaunchJob, DoNotification, DoWebhook)):
            return self, other  # type: ignore[return-value]
        raise TypeError(
            f"Expected an instance of a new action type, got: {type(other).__qualname__!r}"
        )


class RunMetricFilter(Base):
    model_config = ConfigDict(alias_generator=None)  # JSON keys are actual snake_case

    run_filter: SerializedToJson[RunFilter] = Field(default_factory=RunFilter)
    metric_filter: SerializedToJson[MetricFilter]

    def __repr_args__(self) -> _repr.ReprArgs:
        for name, _ in self.model_fields.items():
            if name in self.model_fields_set:
                yield None, getattr(self, name)


class OnLinkArtifact(OnEvent):
    """A new artifact is linked to a collection."""

    event_type: Literal[EventTriggeringConditionType.LINK_MODEL] = Field(
        EventTriggeringConditionType.LINK_MODEL
    )

    scope: ArtifactCollection
    filter: SerializedToJson[EventFilter] = Field(default_factory=EventFilter)


class OnAddArtifactAlias(OnEvent):
    """A new alias is assigned to an artifact."""

    event_type: Literal[EventTriggeringConditionType.ADD_ARTIFACT_ALIAS] = Field(
        EventTriggeringConditionType.ADD_ARTIFACT_ALIAS
    )

    scope: ArtifactCollection | Project
    filter: SerializedToJson[EventFilter]

    @classmethod
    def from_pattern(cls, alias: str, **kwargs: Any) -> Self:
        return cls(
            **kwargs,
            filter=EventFilter(
                filter=on_field("alias").regex_match(alias),
            ),
        )


class OnCreateArtifact(OnEvent):
    """A new artifact is created."""

    event_type: Literal[EventTriggeringConditionType.CREATE_ARTIFACT] = Field(
        EventTriggeringConditionType.CREATE_ARTIFACT
    )

    scope: ArtifactCollection | Project
    filter: SerializedToJson[EventFilter] = Field(default_factory=EventFilter)


class OnRunMetric(OnEvent):
    event_type: Literal[EventTriggeringConditionType.RUN_METRIC] = Field(
        EventTriggeringConditionType.RUN_METRIC
    )

    scope: Project
    filter: SerializedToJson[RunMetricFilter]

    @field_validator("filter", mode="before")
    @classmethod
    def _jsonify_filter(cls, v: Any) -> Any:
        if isinstance(v, MetricFilter):
            # If we're only given a metric threshold condition, assume we trigger on "all runs" in scope
            return jsonify(RunMetricFilter(metric_filter=v))
        return v


# ------------------------------------------------------------------------------
# TODO: Move this, make more generic, and refactor with proper descriptor types
class _RunNameMatchable:
    _name: str

    def __init__(self, name: str):
        self._name = name

    def contains(self, text: str) -> RunFilter:
        # field_name = "display_name"
        return RunFilter.model_validate(
            And(
                inner_operand=[
                    FilterExpression.model_validate({self._name: {"$contains": text}}),
                ],
            )
        )


class _EvaluableMetric(Base):
    model_config = ConfigDict(alias_generator=None)  # JSON keys are actual snake_case

    name: str
    agg_op: Aggregation | None = None
    window_size: PositiveInt = 1

    def agg(self, op: Aggregation, window: int) -> Self:
        self.agg_op = op
        self.window_size = window
        return self

    def mean(self, window: int) -> Self:
        return self.agg(Aggregation.AVERAGE, window)

    def max(self, window: int) -> Self:
        return self.agg(Aggregation.MAX, window)

    def min(self, window: int) -> Self:
        return self.agg(Aggregation.MIN, window)

    def __gt__(self, other: int | float) -> MetricFilter:
        return MetricFilter(
            name=self.name,
            agg_op=self.agg_op,
            window_size=self.window_size,
            threshold=other,
            cmp_op="$gt",
        )

    def __lt__(self, other: int | float) -> MetricFilter:
        return MetricFilter(
            name=self.name,
            agg_op=self.agg_op,
            window_size=self.window_size,
            threshold=other,
            cmp_op="$lt",
        )

    def __ge__(self, other: int | float) -> MetricFilter:
        return MetricFilter(
            name=self.name,
            agg_op=self.agg_op,
            window_size=self.window_size,
            threshold=other,
            cmp_op="$gte",
        )

    def __le__(self, other: int | float) -> MetricFilter:
        return MetricFilter(
            name=self.name,
            agg_op=self.agg_op,
            window_size=self.window_size,
            threshold=other,
            cmp_op="$lte",
        )

    # Aliased method names, for chaining if preferred
    def gt(self, other: int | float) -> MetricFilter:
        return self.__gt__(other)

    def lt(self, other: int | float) -> MetricFilter:
        return self.__lt__(other)

    def gte(self, other: int | float) -> MetricFilter:
        return self.__ge__(other)

    def lte(self, other: int | float) -> MetricFilter:
        return self.__le__(other)


class RunEvent:
    name = _RunNameMatchable(name="display_name")

    @staticmethod
    def metric(name: str) -> _EvaluableMetric:
        return _EvaluableMetric(name=name)


class Artifact:
    @staticmethod
    def created(scope: ArtifactCollection) -> OnCreateArtifact:
        # TODO: Define scope more consistently with other event types
        return OnCreateArtifact(scope=scope)


RunFilter.model_rebuild()
MetricFilter.model_rebuild()
RunMetricFilter.model_rebuild()
EventFilter.model_rebuild()
