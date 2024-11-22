"""Events that trigger W&B Automations."""

from __future__ import annotations

import sys
from enum import Enum
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import ConfigDict, Field, Json, PositiveInt, field_validator
from pydantic._internal import _repr

from ._base import Base, SerializedToJson
from ._filters import And, FilteredField, Gt, Gte, Lt, Lte
from ._filters.filter import AnyExpr
from ._generated import EventTriggeringConditionType
from .actions import DoLaunchJob, DoNotification, DoWebhook
from .scopes import ArtifactCollection, Project

if TYPE_CHECKING:
    from .automations import ActionInputT, EventAndActionInput, EventInputT

if sys.version_info >= (3, 12):
    from typing import Self, override
else:
    from typing_extensions import Self, override


# TODO: Find a way to autogenerate this too
class Agg(str, Enum):
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


# Note: The GQL input for "eventFilter" does not wrap the filter in an extra `filter` key, unlike the
# eventFilter returned in responses
InputEventFilter = AnyExpr


class MetricFilter(Base):
    model_config = ConfigDict(alias_generator=None)  # JSON fields here are snake_case

    name: str
    window_size: PositiveInt = Field(
        default=1,
        le=10,  # NOTE: For now, enforce maximum window size of 10 here
    )
    agg_op: Agg | None = None
    cmp_op: Literal["$gte", "$gt", "$lt", "$lte"]
    threshold: int | float

    def __and__(self, other: RunFilter) -> RunMetricFilter:
        if isinstance(other, RunFilter):
            return RunMetricFilter(run_filter=other, metric_filter=self)
        raise NotImplementedError

    _OP_MAP: Final[dict[str, str]] = {
        Gte.OP: ">=",
        Gt.OP: ">",
        Lte.OP: "<=",
        Lt.OP: "<",
    }

    def __repr__(self) -> str:
        cls_name = type(self).__qualname__

        metric = f"`{self.name}`"

        left = f"{agg.value}({metric})" if (agg := self.agg_op) else metric
        op = self._OP_MAP[self.cmp_op]
        right = f"{self.threshold}"

        expr = f"{left} {op} {right}"

        return f"{cls_name}({expr!r})"


class OnEvent(Base):
    event_type: EventTriggeringConditionType
    scope: ArtifactCollection | Project
    filter: Json[InputEventFilter | RunMetricFilter]

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

    event_type: Literal[EventTriggeringConditionType.LINK_MODEL] = (
        EventTriggeringConditionType.LINK_MODEL
    )

    scope: ArtifactCollection
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)


class OnAddArtifactAlias(OnEvent):
    """A new alias is assigned to an artifact."""

    event_type: Literal[EventTriggeringConditionType.ADD_ARTIFACT_ALIAS] = (
        EventTriggeringConditionType.ADD_ARTIFACT_ALIAS
    )

    scope: ArtifactCollection | Project
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)

    @classmethod
    def from_pattern(cls, alias: str, *, scope: ArtifactCollection | Project) -> Self:
        return cls(
            scope=scope,
            filter=FilteredField("alias").regex_match(alias),
        )


class OnCreateArtifact(OnEvent):
    """A new artifact is created."""

    event_type: Literal[EventTriggeringConditionType.CREATE_ARTIFACT] = (
        EventTriggeringConditionType.CREATE_ARTIFACT
    )

    scope: ArtifactCollection | Project
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)


class OnRunMetric(OnEvent):
    event_type: Literal[EventTriggeringConditionType.RUN_METRIC] = Field(
        EventTriggeringConditionType.RUN_METRIC
    )

    scope: Project
    filter: SerializedToJson[RunMetricFilter]

    @field_validator("filter", mode="before")
    @classmethod
    def _wrap_metric_filter(cls, v: Any) -> Any:
        if isinstance(v, MetricFilter):
            # If we're only given a metric threshold condition, assume we trigger on "all runs" in scope
            return RunMetricFilter(metric_filter=v)
        return v


# ------------------------------------------------------------------------------
# TODO: fix/refactor correctly with consistent descriptor types
class _QueryableField:
    _name: str
    _owner: type

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name
        self._owner = owner

    def _field_name(self) -> str:
        if issubclass(self._owner, RunEvent) and (self._name == "name"):
            # Users who wish to filter on `Run.name` actually need to filter on `Run.display_name`
            # in the backend.
            # We can't reasonably expect them to know this a priori, so automatically fix it here.
            return "display_name"

        return self._name

    def contains(self, text: str) -> RunFilter:
        filter_expr = FilteredField(self._field_name()).contains(text)
        return RunFilter(other=[filter_expr])


class _MetricOperand(Base):
    model_config = ConfigDict(alias_generator=None)  # JSON keys are actual snake_case

    name: str
    agg_op: Agg | None = None
    window_size: PositiveInt = 1

    def average(self, window: int) -> Self:
        return self.model_copy(update={"agg_op": Agg.AVERAGE, "window_size": window})

    # Method alias for users who will likely be familiar with naming conventions
    # from e.g. torch/tf/numpy/pandas/polars/etc.
    def mean(self, window: int) -> Self:
        return self.average(window=window)

    def max(self, window: int) -> Self:
        return self.model_copy(update={"agg_op": Agg.MAX, "window_size": window})

    def min(self, window: int) -> Self:
        return self.model_copy(update={"agg_op": Agg.MIN, "window_size": window})

    def __gt__(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op=Gt.OP)

    def __lt__(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op=Lt.OP)

    def __ge__(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op=Gte.OP)

    def __le__(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op=Lte.OP)

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
    name = _QueryableField()

    @staticmethod
    def metric(name: str) -> _MetricOperand:
        return _MetricOperand(name=name)


class ArtifactEvent:
    @staticmethod
    def created(scope: ArtifactCollection) -> OnCreateArtifact:
        # TODO: Define scope more consistently with other event types
        return OnCreateArtifact(scope=scope)


RunFilter.model_rebuild()
MetricFilter.model_rebuild()
RunMetricFilter.model_rebuild()
EventFilter.model_rebuild()
