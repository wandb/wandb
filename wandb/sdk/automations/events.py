"""Events that trigger W&B Automations."""

from __future__ import annotations

import sys
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal, Union, overload

from pydantic import (
    AfterValidator,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    PositiveInt,
    Tag,
    field_validator,
)
from pydantic._internal import _repr

from wandb.sdk.automations.filters._operators import OpDict

from ._generated import Base, EventTriggeringConditionType, GQLBase, SerializedToJson
from ._utils import get_scope_type
from ._validators import mongo_op_to_python, python_op_to_mongo, uppercase_if_str
from .actions import _ActionInput
from .filters import And, FilterField, Gt, Gte, Lt, Lte, Or
from .filters._expressions import AnyOpDict, FilterExpr
from .scopes import ArtifactCollectionScope, ProjectScope, ScopeType

if TYPE_CHECKING:
    from .automations import NewAutomation, _ActionInputT

if sys.version_info >= (3, 12):
    from typing import Annotated, Self
else:
    from typing_extensions import Annotated, Self


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
InputEventFilter = Union[AnyOpDict, FilterExpr]


class _WrappedEventFilter(GQLBase):
    filter: SerializedToJson[InputEventFilter] = Field(default_factory=And)


def _wrap_or_and(v: Any) -> Or:
    """Ensure the given filter is wrapped inside $or -> $and operators, like `{"$or": [{"$and": [...]}]}`.

    This is necessary when the frontend expects this format.
    """
    # Check if the filter is already wrapped as needed
    if (
        Or.__pydantic_validator__.isinstance_python(v)
        and v.inner
        and And.__pydantic_validator__.isinstance_python(v.inner[0])
    ):
        return Or.model_validate(v)

    if And.__pydantic_validator__.isinstance_python(v):
        return Or(inner=[v])

    return Or(inner=[And(inner=[v])])


def _wrap_and(v: Any) -> And:
    if And.__pydantic_validator__.isinstance_python(v):
        return And.model_validate(v)
    return And(inner=[v])


@lru_cache(maxsize=1)
def _empty_or_and() -> Or:
    return Or(inner=[And(inner=[])])


class MetricFilter(GQLBase):
    model_config = ConfigDict(alias_generator=None)  # JSON fields here are snake_case

    name: str
    window_size: PositiveInt = Field(default=1)
    agg_op: Annotated[
        Agg | None,
        BeforeValidator(uppercase_if_str),  # Be helpful: e.g. "min" -> "MIN"
    ]
    cmp_op: Annotated[
        Literal["$gte", "$gt", "$lt", "$lte"],
        BeforeValidator(python_op_to_mongo),  # Be helpful: e.g. ">" -> "$gt"
    ]
    threshold: int | float

    @overload
    def __and__(self, other: OpDict | FilterExpr) -> RunMetricFilter: ...
    @overload
    def __and__(self, other: Any) -> Any: ...

    def __and__(self, other: OpDict | FilterExpr | Any) -> RunMetricFilter | Any:
        if isinstance(other, (OpDict, FilterExpr)):
            return RunMetricFilter(run_filter=other, metric_filter=self)
        return other.__and__(self)  # Try switching the order of operands

    def __repr_args__(self) -> _repr.ReprArgs:
        metric = self.name

        left = f"{agg.value}(`{metric}`)" if (agg := self.agg_op) else f"`{metric}`"
        op = mongo_op_to_python(self.cmp_op)
        right = f"{self.threshold}"

        expr = rf"{left} {op} {right}"
        yield None, expr


class RunMetricFilter(GQLBase):
    model_config = ConfigDict(alias_generator=None)  # JSON keys are actual snake_case

    run_filter: Annotated[
        SerializedToJson[AnyOpDict | FilterExpr],
        AfterValidator(_wrap_and),
    ] = Field(default_factory=And)
    metric_filter: SerializedToJson[MetricFilter]


class _EventInput(GQLBase):
    event_type: EventType

    scope: ArtifactCollectionScope | ProjectScope
    filter: SerializedToJson[InputEventFilter] | SerializedToJson[RunMetricFilter]

    def add_action(self, action: _ActionInputT) -> NewAutomation:
        """Define an executed action to be triggered by this event."""
        from .automations import NewAutomation

        if isinstance(action, _ActionInput):
            return NewAutomation(scope=self.scope, event=self, action=action)

        raise TypeError(f"Expected a valid action, got: {type(action).__qualname__!r}")

    def __rshift__(self, other: _ActionInputT) -> NewAutomation:
        """Supports syntactic sugar to define the action triggered by this event as: `event >> action`."""
        return self.add_action(other)


class OnLinkArtifact(_EventInput):
    """A new artifact is linked to a collection."""

    event_type: Literal[EventType.LINK_MODEL] = EventType.LINK_MODEL

    scope: ArtifactCollectionScope
    filter: Annotated[
        SerializedToJson[InputEventFilter],
        Field(default_factory=_empty_or_and),
        AfterValidator(_wrap_or_and),
    ]


class OnAddArtifactAlias(_EventInput):
    """A new alias is assigned to an artifact."""

    event_type: Literal[EventType.ADD_ARTIFACT_ALIAS] = EventType.ADD_ARTIFACT_ALIAS

    scope: Annotated[
        Union[
            Annotated[ArtifactCollectionScope, Tag(ScopeType.ARTIFACT_COLLECTION)],
            Annotated[ProjectScope, Tag(ScopeType.PROJECT)],
        ],
        Discriminator(get_scope_type),
    ]
    filter: Annotated[
        SerializedToJson[InputEventFilter],
        Field(default_factory=_empty_or_and),
        AfterValidator(_wrap_or_and),
    ]


class OnCreateArtifact(_EventInput):
    """A new artifact is created."""

    event_type: Literal[EventType.CREATE_ARTIFACT] = EventType.CREATE_ARTIFACT

    scope: Annotated[
        Union[
            Annotated[ArtifactCollectionScope, Tag(ScopeType.ARTIFACT_COLLECTION)],
            Annotated[ProjectScope, Tag(ScopeType.PROJECT)],
        ],
        Discriminator(get_scope_type),
    ]
    filter: Annotated[
        SerializedToJson[InputEventFilter],
        Field(default_factory=_empty_or_and),
        AfterValidator(_wrap_or_and),
    ]


class OnRunMetric(_EventInput):
    """A run metric satisfies a condition."""

    event_type: Literal[EventType.RUN_METRIC] = EventType.RUN_METRIC

    scope: ProjectScope
    filter: SerializedToJson[RunMetricFilter]

    @field_validator("filter", mode="before")
    @classmethod
    def _wrap_metric_filter(cls, v: Any) -> Any:
        if MetricFilter.__pydantic_validator__.isinstance_python(v):
            # If we're only given a metric threshold condition, assume we trigger on "all runs" in scope
            return RunMetricFilter(metric_filter=v)
        return v


# ----------------------------------------------------------------------------
class _QueryableField:
    _name: str | None

    def __init__(self, alias: str | None = None):
        self._name = alias

    def __set_name__(self, owner: type, name: str) -> None:
        # Automatically set the name of the field to the name of the property,
        # unless it was set explicitly before.
        if self._name is None:
            self._name = name

    def __get__(self, obj: Any, objtype: type) -> FilterField:
        return FilterField(self._name)


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


MetricFilter.model_rebuild()
RunMetricFilter.model_rebuild()
_WrappedEventFilter.model_rebuild()

OnLinkArtifact.model_rebuild()
OnAddArtifactAlias.model_rebuild()
OnCreateArtifact.model_rebuild()
OnRunMetric.model_rebuild()
