"""Events that trigger W&B Automations."""

from __future__ import annotations

import sys
from enum import Enum
from typing import TYPE_CHECKING, Any, Final, Literal, Union

from pydantic import (
    ConfigDict,
    Discriminator,
    Field,
    Json,
    PositiveInt,
    Tag,
    field_validator,
)
from pydantic._internal import _repr

from ._base import Base, SerializedToJson
from ._filters import And, FilteredField, Gt, Gte, Lt, Lte
from ._filters.filter_expr import AnyExpr
from ._generated import EventTriggeringConditionType
from .actions import DoNotification, DoWebhook
from .scopes import ArtifactCollection, Project, ScopeType, get_scope

if TYPE_CHECKING:
    from .automations import ActionInputT, EventAndActionInput, EventInputT

if sys.version_info >= (3, 12):
    from typing import Annotated, Self, override
else:
    from typing_extensions import Annotated, Self, override


# TODO: Find a way to autogenerate this too
class Agg(str, Enum):
    MAX = "MAX"
    MIN = "MIN"
    AVERAGE = "AVERAGE"


# NOTE: Enum is aliased to a shorter name for readability,
# in a public module for easier access
EventType = EventTriggeringConditionType
"""The type of event that triggers an automation."""


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


_OP2SYM: Final[dict[str, str]] = {
    Gte.OP: ">=",
    Gt.OP: ">",
    Lte.OP: "<=",
    Lt.OP: "<",
}


class MetricFilter(Base):
    model_config = ConfigDict(alias_generator=None)  # JSON fields here are snake_case

    name: str
    window_size: PositiveInt = Field(default=1)
    agg_op: Agg | None = None
    cmp_op: Literal["$gte", "$gt", "$lt", "$lte"]
    threshold: int | float

    def __and__(self, other: RunFilter) -> RunMetricFilter:
        if isinstance(other, RunFilter):
            return RunMetricFilter(run_filter=other, metric_filter=self)
        raise NotImplementedError

    def __repr_args__(self) -> _repr.ReprArgs:
        metric = f"`{self.name}`"

        left = f"{agg.value}({metric})" if (agg := self.agg_op) else metric
        op = _OP2SYM[self.cmp_op]
        right = f"{self.threshold}"

        expr = f"{left} {op} {right}"
        yield None, expr


class OnEvent(Base):
    event_type: EventType
    scope: ArtifactCollection | Project
    filter: Json[InputEventFilter | RunMetricFilter]

    def add_action(
        self, action: ActionInputT
    ) -> EventAndActionInput[EventInputT, ActionInputT]:
        """Define an executed action to be triggered by this event."""
        if isinstance(action, (DoNotification, DoWebhook)):
            return self, action  # type: ignore[return-value]
        raise TypeError(f"Expected a valid action, got: {type(action).__qualname__!r}")

    def __rshift__(
        self, other: ActionInputT
    ) -> EventAndActionInput[EventInputT, ActionInputT]:
        """Supports syntactic sugar to define the action triggered by this event as: `event >> action`."""
        return self.add_action(other)


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

    event_type: Literal[EventType.LINK_MODEL] = EventType.LINK_MODEL

    scope: ArtifactCollection
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)


class OnAddArtifactAlias(OnEvent):
    """A new alias is assigned to an artifact."""

    event_type: Literal[EventType.ADD_ARTIFACT_ALIAS] = EventType.ADD_ARTIFACT_ALIAS

    scope: Annotated[
        Union[
            Annotated[ArtifactCollection, Tag(ScopeType.ARTIFACT_COLLECTION)],
            Annotated[Project, Tag(ScopeType.PROJECT)],
        ],
        Discriminator(get_scope),
    ]
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)

    @classmethod
    def from_pattern(cls, alias: str, *, scope: ArtifactCollection | Project) -> Self:
        return cls(
            scope=scope,
            filter=FilteredField("alias").regex_match(alias),
        )


class OnCreateArtifact(OnEvent):
    """A new artifact is created."""

    event_type: Literal[EventType.CREATE_ARTIFACT] = EventType.CREATE_ARTIFACT

    scope: Annotated[
        Union[
            Annotated[ArtifactCollection, Tag(ScopeType.ARTIFACT_COLLECTION)],
            Annotated[Project, Tag(ScopeType.PROJECT)],
        ],
        Discriminator(get_scope),
    ]
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)


class OnRunMetric(OnEvent):
    event_type: Literal[EventType.RUN_METRIC] = EventType.RUN_METRIC

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
    _alias: str | None
    _name: str
    _owner: type

    def __init__(self, alias: str | None = None):
        self._alias = alias

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name
        self._owner = owner

    # def _field_name(self) -> str:
    #     if issubclass(self._owner, RunEvent) and (self._name == "name"):
    #         # `Run.name` is actually filtered on `Run.display_name` in the backend.
    #         # We can't reasonably expect users to know this a priori, so
    #         # automatically fix it here.
    #         return "display_name"
    #     return self._name

    def contains(self, text: str) -> RunFilter:
        filter_expr = FilteredField(self._alias or self._name).contains(text)
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
    name = _QueryableField("display_name")
    # `Run.name` is actually filtered on `Run.display_name` in the backend.
    # We can't reasonably expect users to know this a priori, so
    # automatically fix it here.

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
