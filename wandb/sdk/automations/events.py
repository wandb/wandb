"""Events that trigger W&B Automations."""

from __future__ import annotations

import sys
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Final, Literal, Union

from pydantic import ConfigDict, Discriminator, Field, PositiveInt, Tag, field_validator
from pydantic._internal import _repr

from ._generated import Base, EventTriggeringConditionType, SerializedToJson
from ._utils import get_scope_type
from .actions import DoNothing, DoNotification, DoWebhook
from .filters import And, Eq, Gt, Gte, Lt, Lte, Ne, Or
from .filters._expressions import AnyOp, FilterExpr
from .scopes import ArtifactCollectionScope, ProjectScope, ScopeType

if TYPE_CHECKING:
    from .automations import NewAutomation, _ActionInputT

if sys.version_info >= (3, 12):
    from typing import Annotated, Self, override
else:
    from typing_extensions import Annotated, Self, override


class Agg(str, Enum):
    """Supported aggregation operations."""

    MAX = "MAX"
    MIN = "MIN"
    AVERAGE = "AVERAGE"


# NOTE: Name shortened for readability and defined publicly for easier access
EventType = EventTriggeringConditionType
"""The type of event that triggers an automation."""


# Note: The GQL input for "eventFilter" does not wrap the filter in an extra `filter` key, unlike the
# eventFilter returned in responses
InputEventFilter = Union[AnyOp, FilterExpr, Dict[str, Any]]


class _WrappedEventFilter(Base):
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)


class RunFilter(And):
    @override
    def __and__(self, other: MetricFilter) -> RunMetricFilter:  # type: ignore[override]
        if isinstance(other, MetricFilter):
            return RunMetricFilter(run_filter=self, metric_filter=other)
        return NotImplemented


_MONGO2PYTHON_OPS: Final[dict[str, str]] = {
    Eq.OP: "==",
    Ne.OP: "!=",
    Gt.OP: ">",
    Lt.OP: "<",
    Gte.OP: ">=",
    Lte.OP: "<=",
}
"""Maps MongoDB comparison operators to their Python literal representations."""


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
        return NotImplemented

    def __repr_args__(self) -> _repr.ReprArgs:
        metric = f"`{self.name}`"

        left = f"{agg.value}({metric})" if (agg := self.agg_op) else metric
        op = _MONGO2PYTHON_OPS[self.cmp_op]
        right = f"{self.threshold}"

        expr = f"{left} {op} {right}"
        yield None, expr


class _OnEvent(Base):
    scope: ArtifactCollectionScope | ProjectScope
    filter: SerializedToJson[InputEventFilter] | SerializedToJson[RunMetricFilter]

    def add_action(self, action: _ActionInputT) -> NewAutomation:
        """Define an executed action to be triggered by this event."""
        from .automations import NewAutomation

        if isinstance(action, (DoNotification, DoWebhook, DoNothing)):
            return NewAutomation(scope=self.scope, event=self, action=action)

        raise TypeError(f"Expected a valid action, got: {type(action).__qualname__!r}")

    def __rshift__(self, other: _ActionInputT) -> NewAutomation:
        """Supports syntactic sugar to define the action triggered by this event as: `event >> action`."""
        return self.add_action(other)


class RunMetricFilter(Base):
    model_config = ConfigDict(alias_generator=None)  # JSON keys are actual snake_case

    run_filter: SerializedToJson[RunFilter] = Field(default_factory=RunFilter)
    metric_filter: SerializedToJson[MetricFilter]

    def __repr_args__(self) -> _repr.ReprArgs:
        # Display set field values as positional args
        for field, value in self:
            if field in self.model_fields_set:
                yield None, value


def _wrap_or_and(v: Any) -> Or:
    """Ensure the given filter is wrapped inside $or -> $and operators, like `{"$or": [{"$and": [...]}]}`.

    This is necessary when the frontend expects this format.
    """
    if isinstance(v, And):
        return Or(other=[v])
    if isinstance(v, Or):
        if len(v.other) == 1:
            if isinstance(inner := v.other[0], And):
                return v
            else:
                return Or(other=[And(other=[inner])])
    return Or(other=[And(other=[v])])


class OnLinkArtifact(_OnEvent):
    """A new artifact is linked to a collection."""

    event_type: Literal[EventType.LINK_MODEL] = EventType.LINK_MODEL

    scope: ArtifactCollectionScope
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)


class OnAddArtifactAlias(_OnEvent):
    """A new alias is assigned to an artifact."""

    event_type: Literal[EventType.ADD_ARTIFACT_ALIAS] = EventType.ADD_ARTIFACT_ALIAS

    scope: Annotated[
        Union[
            Annotated[ArtifactCollectionScope, Tag(ScopeType.ARTIFACT_COLLECTION)],
            Annotated[ProjectScope, Tag(ScopeType.PROJECT)],
        ],
        Discriminator(get_scope_type),
    ]
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)


class OnCreateArtifact(_OnEvent):
    """A new artifact is created."""

    event_type: Literal[EventType.CREATE_ARTIFACT] = EventType.CREATE_ARTIFACT

    scope: Annotated[
        Union[
            Annotated[ArtifactCollectionScope, Tag(ScopeType.ARTIFACT_COLLECTION)],
            Annotated[ProjectScope, Tag(ScopeType.PROJECT)],
        ],
        Discriminator(get_scope_type),
    ]
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)


class OnRunMetric(_OnEvent):
    """A run metric satisfies a condition."""

    event_type: Literal[EventType.RUN_METRIC] = EventType.RUN_METRIC

    scope: ProjectScope
    filter: SerializedToJson[RunMetricFilter]

    @field_validator("filter", mode="before")
    @classmethod
    def _wrap_metric_filter(cls, v: Any) -> Any:
        if isinstance(v, MetricFilter):
            # If we're only given a metric threshold condition, assume we trigger on "all runs" in scope
            return RunMetricFilter(metric_filter=v)
        return v


# ----------------------------------------------------------------------------
class _QueryableField:
    _field_name: str | None

    def __init__(self, alias: str | None = None):
        self._field_name = alias

    def __set_name__(self, owner: type, name: str) -> None:
        # Automatically set the name of the field to the name of the property,
        # unless it was set explicitly before.
        if self._field_name is None:
            self._field_name = name

    # def __get__(self, obj: Any, objtype: type) -> FilterField:
    #     return FilterField(self._field_name)

    def contains(self, text: str) -> RunFilter:
        return RunFilter(other=[{self._field_name: {"$contains": text}}])

    def matches_regex(self, pattern: str) -> RunFilter:
        return RunFilter(other=[{self._field_name: {"$regex": pattern}}])


class _MetricOperand(Base):
    model_config = ConfigDict(alias_generator=None)  # JSON keys are actual snake_case

    name: str
    agg_op: Agg | None = None
    window_size: PositiveInt = 1

    def agg(self, op: Agg, window: int) -> Self:
        if self.agg_op is not None:
            raise ValueError(f"Aggregation operator already set as: {self.agg_op!r}")
        return self.model_copy(update={"agg_op": op, "window_size": window})

    def max(self, window: int) -> Self:
        return self.agg(Agg.MAX, window)

    def min(self, window: int) -> Self:
        return self.agg(Agg.MIN, window)

    def average(self, window: int) -> Self:
        return self.agg(Agg.AVERAGE, window)

    # Aliased method for users familiar with e.g. torch/tf/numpy/pandas/polars/etc.
    def mean(self, window: int) -> Self:
        return self.average(window=window)

    def gt(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op=Gt.OP)

    def lt(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op=Lt.OP)

    def gte(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op=Gte.OP)

    def lte(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op=Lte.OP)

    __gt__ = gt
    __lt__ = lt
    __ge__ = gte
    __le__ = lte


class RunEvent:
    name = _QueryableField("display_name")
    # `Run.name` is actually filtered on `Run.display_name` in the backend.
    # We can't reasonably expect users to know this a priori, so
    # automatically fix it here.

    @staticmethod
    def metric(name: str) -> _MetricOperand:
        """Define a metric filter condition."""
        return _MetricOperand(name=name)


class ArtifactEvent:
    alias = _QueryableField()


RunFilter.model_rebuild()
MetricFilter.model_rebuild()
RunMetricFilter.model_rebuild()
_WrappedEventFilter.model_rebuild()

OnLinkArtifact.model_rebuild()
OnAddArtifactAlias.model_rebuild()
OnCreateArtifact.model_rebuild()
OnRunMetric.model_rebuild()
