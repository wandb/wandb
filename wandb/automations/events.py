"""Events that trigger W&B Automations."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Optional, Union, overload

from pydantic import Field, PositiveInt, StrictFloat, StrictInt
from typing_extensions import Self, get_args, override

from wandb._pydantic import (
    IS_PYDANTIC_V2,
    Base,
    GQLBase,
    SerializedToJson,
    field_validator,
    model_validator,
    pydantic_isinstance,
    to_json,
)

from ._filters import And, FilterExpr, FilterField, MongoOpOrFilter, Or
from ._filters.operators import BaseOp, Op, RichReprResult
from ._generated import EventTriggeringConditionType, FilterEventFields
from ._validators import (
    MONGO2PY_OPS,
    PY2MONGO_OPS,
    ensure_json,
    simplify_ops,
    validate_scope,
)
from .actions import InputAction, InputActionTypes
from .scopes import ArtifactCollectionScope, InputScope, ProjectScope

if TYPE_CHECKING:
    from .automations import NewAutomation


class Agg(str, Enum):
    """Supported metric aggregation operations."""

    MAX = "MAX"
    MIN = "MIN"
    AVERAGE = "AVERAGE"


# NOTE: Name shortened for readability and defined publicly for easier access
EventType = EventTriggeringConditionType
"""The type of event that triggers an automation."""


# ------------------------------------------------------------------------------
# Saved types: for parsing response data from saved automations


# Note: In GQL responses with saved automations, the filter is wrapped in an extra `filter` key.
class SavedWrappedFilter(GQLBase):
    filter: SerializedToJson[Union[Op, FilterExpr]] = Field(default_factory=And)

    if not IS_PYDANTIC_V2:  # Hack for v1 compatibility
        _fix_json = field_validator("filter", mode="before")(ensure_json)


class MetricFilter(GQLBase):
    name: str
    window: PositiveInt = Field(default=1, alias="window_size")
    agg: Optional[Agg] = Field(default=None, alias="agg_op")

    cmp: Literal["$gte", "$gt", "$lt", "$lte"] = Field(alias="cmp_op")

    threshold: Union[StrictInt, StrictFloat]

    @field_validator("agg", mode="before")
    def _validate_agg_op(cls, v: Any) -> Any:
        # Be helpful: e.g. "min" -> "MIN"
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("cmp", mode="before")
    def _validate_cmp_op(cls, v: Any) -> Any:
        # Be helpful: e.g. ">" -> "$gt"
        return PY2MONGO_OPS.get(v.strip(), v) if isinstance(v, str) else v

    @overload
    def __and__(self, other: BaseOp | FilterExpr) -> RunMetricFilter: ...
    @overload
    def __and__(self, other: Any) -> Any: ...

    def __and__(self, other: BaseOp | FilterExpr | Any) -> RunMetricFilter | Any:
        if isinstance(other, (BaseOp, FilterExpr)):
            return RunMetricFilter(run_filter=other, metric_filter=self)
        return other.__and__(self)  # Try switching the order of operands

    def __repr__(self) -> str:
        left = f"{self.agg.value}({self.name})" if self.agg else self.name
        op = MONGO2PY_OPS.get(self.cmp, self.cmp)
        right = f"{self.threshold}"
        expr = rf"{left} {op} {right}"
        return repr(expr)

    @override
    def __rich_repr__(self) -> RichReprResult:  # type: ignore[override]
        yield None, repr(self)


class RunMetricFilter(GQLBase):
    run_filter: SerializedToJson[Union[Op, FilterExpr]] = Field(default_factory=And)
    metric_filter: SerializedToJson[MetricFilter]

    @model_validator(mode="before")
    @classmethod
    def _wrap_metric_filter(cls, v: Any) -> Any:
        if pydantic_isinstance(v, MetricFilter):
            # If we're only given a metric filter, assume we trigger on "all runs" in scope
            return cls(metric_filter=v)
        return v

    @field_validator("run_filter", mode="after")
    def _wrap_run_filter(cls, v: Op | FilterExpr) -> Any:
        v_new = simplify_ops(v)
        return (
            And.model_validate(v_new)
            if pydantic_isinstance(v_new, And)
            else And(and_=[v_new])
        )

    if not IS_PYDANTIC_V2:  # Hack for v1 compatibility
        _fix_json = field_validator("run_filter", "metric_filter", mode="before")(
            ensure_json
        )


class SavedFilterEvent(FilterEventFields):
    """A more introspection-friendly representation of a triggering event from a saved automation."""

    # We override the type of the `filter` field since the original GraphQL
    # schema (and generated class) defines it as a String, when we know it's
    # actually a JSONString.
    filter: SerializedToJson[Union[SavedWrappedFilter, RunMetricFilter]]

    def __repr_name__(self) -> str:  # type: ignore[override]
        return self.event_type.value

    if not IS_PYDANTIC_V2:  # Hack for v1 compatibility

        @field_validator("filter", mode="before")
        def _validate_json_fields(cls, v: Any) -> Any:
            # the Json type expects to parse a JSON-serialized object, so re-serialize it first if needed
            return v if isinstance(v, (str, bytes)) else to_json(v)


# ------------------------------------------------------------------------------
# Input types: for creating or updating automations


# Note: The GQL input for "eventFilter" does NOT wrap the filter in an extra `filter` key, unlike the
# eventFilter returned in responses for saved automations.
class _BaseEventInput(GQLBase):
    event_type: EventType

    scope: InputScope = Field(discriminator="typename__")
    filter: SerializedToJson[Any]

    @field_validator("scope", mode="before")
    def _validate_scope(cls, v: Any) -> Any:
        return validate_scope(v)

    def add_action(self, action: InputAction) -> NewAutomation:
        """Define an executed action to be triggered by this event."""
        from .automations import NewAutomation

        if isinstance(action, InputActionTypes):
            return NewAutomation(scope=self.scope, event=self, action=action)

        raise TypeError(f"Expected a valid action, got: {type(action).__qualname__!r}")

    def __rshift__(self, other: InputAction) -> NewAutomation:
        """Supports `event >> action` as syntactic sugar to combine an event and action."""
        return self.add_action(other)

    if not IS_PYDANTIC_V2:  # Hack for v1 compatibility
        _fix_json = field_validator("filter", mode="before")(ensure_json)


class _BaseMutationEventInput(_BaseEventInput):
    event_type: EventType
    scope: InputScope
    filter: SerializedToJson[MongoOpOrFilter] = Field(default_factory=And)

    @field_validator("filter", mode="after")
    def _wrap_filter(cls, v: Any) -> Any:
        """Ensure the given filter is wrapped inside $or -> $and operators: `{"$or": [{"$and": [...]}]}`.

        This is awkward but necessary because the frontend expects this format.
        """
        v_new = simplify_ops(v)
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
class _QueryableField:
    _filter_name: str | None  #: The name of the field to filter on in the backend.
    _python_name: str  #: The name of the field in the assigned Python class.

    def __init__(self, server_name: str | None = None):
        self._filter_name = server_name

    def __set_name__(self, owner: type, name: str) -> None:
        self._python_name = name

    def __get__(self, obj: Any, objtype: type) -> FilterField:
        # By default, if we didn't explicitly provide a backend name for
        # filtering, assume the field has the same name in the backend as
        # the python attribute.
        return FilterField(self._filter_name or self._python_name)


class _MetricOperand(Base):
    name: str
    agg: Optional[Agg] = Field(default=None, alias="agg_op")
    window: PositiveInt = Field(default=1, alias="window_size")

    def _agg(self, op: Agg, window: int) -> Self:
        if self.agg is not None:
            raise ValueError(f"Aggregation operator already set as: {self.agg!r}")
        return self.model_copy(update={"agg": op, "window": window})

    def max(self, window: int) -> Self:
        return self._agg(Agg.MAX, window)

    def min(self, window: int) -> Self:
        return self._agg(Agg.MIN, window)

    def average(self, window: int) -> Self:
        return self._agg(Agg.AVERAGE, window)

    # Aliased method for users familiar with e.g. torch/tf/numpy/pandas/polars/etc.
    def mean(self, window: int) -> Self:
        return self.average(window=window)

    def gt(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op="$gt")

    def lt(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op="$lt")

    def gte(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op="$gte")

    def lte(self, other: int | float) -> MetricFilter:
        return MetricFilter(**self.model_dump(), threshold=other, cmp_op="$lte")

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
SavedWrappedFilter.model_rebuild()

OnLinkArtifact.model_rebuild()
OnAddArtifactAlias.model_rebuild()
OnCreateArtifact.model_rebuild()
OnRunMetric.model_rebuild()
