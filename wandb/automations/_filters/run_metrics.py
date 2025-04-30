# ruff: noqa: UP007

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Literal, Optional, Union

from pydantic import Field, PositiveInt, StrictFloat, StrictInt, field_validator
from typing_extensions import Annotated, override

from wandb._pydantic import GQLBase
from wandb.automations._validators import LenientStrEnum

from .expressions import FilterExpr
from .operators import BaseOp, RichReprResult

if TYPE_CHECKING:
    from wandb.automations.events import RunMetricFilter

# Maps MongoDB comparison operators -> Python literal (str) representations
MONGO2PY_OPS: Final[dict[str, str]] = {
    "$eq": "==",
    "$ne": "!=",
    "$gt": ">",
    "$lt": "<",
    "$gte": ">=",
    "$lte": "<=",
}
# Reverse mapping from Python literal (str) -> MongoDB operator key
PY2MONGO_OPS: Final[dict[str, str]] = {v: k for k, v in MONGO2PY_OPS.items()}


class Agg(LenientStrEnum):  # wandb/core: `Aggregation`
    """Supported run metric aggregation operations."""

    MAX = "MAX"
    MIN = "MIN"
    AVERAGE = "AVERAGE"


class ChangeType(LenientStrEnum):  # wandb/core: `RunMetricChangeType`
    """Describes the metric change as absolute (arithmetic difference) or relative (decimal percentage)."""

    ABSOLUTE = "ABSOLUTE"
    RELATIVE = "RELATIVE"


class ChangeDirection(LenientStrEnum):  # wandb/core: `RunMetricChangeDirection`
    """Describes the direction of the metric change."""

    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    ANY = "ANY"


class BaseMetricFilter(GQLBase):
    name: str
    """Name of the observed metric."""

    agg: Optional[Agg]
    """Aggregation operation, if any, to apply over the window size."""

    window: PositiveInt
    """Size of the window over which the metric is aggregated."""

    # ------------------------------------------------------------------------------

    threshold: Union[StrictInt, StrictFloat]
    """Threshold value to compare against."""

    def __and__(self, other: Any) -> RunMetricFilter:
        """Supports syntactic sugar for defining a RunMetricEvent from `metric_filter & run_filter`."""
        from wandb.automations.events import RunMetricFilter

        if isinstance(run_filter := other, (BaseOp, FilterExpr)):
            # Assume `other` is a run filter, and we are building a RunMetricEvent.
            # For the metric filter, delegate to the inner validator(s) to further wrap/nest as appropriate.
            return RunMetricFilter(run=run_filter, metric=self)
        return NotImplemented

    def __rand__(self, other: BaseOp | FilterExpr) -> RunMetricFilter:
        """Ensures `&` is commutative when using it to define a RunMetricEvent: `run_filter & metric_filter == metric_filter & run_filter`."""
        return self.__and__(other)


class MetricThresholdFilter(BaseMetricFilter):  # wandb/core: `RunMetricThresholdFilter`
    """Defines a filter that compares a run metric against a user-defined threshold value."""

    name: str
    agg: Annotated[Optional[Agg], Field(alias="agg_op")] = None
    window: Annotated[PositiveInt, Field(alias="window_size")] = 1

    cmp: Annotated[Literal["$gte", "$gt", "$lt", "$lte"], Field(alias="cmp_op")]
    """Comparison operator used to compare the metric value (left) vs. the threshold value (right)."""

    threshold: Union[StrictInt, StrictFloat]

    @field_validator("cmp", mode="before")
    def _validate_cmp(cls, v: Any) -> Any:
        # Be helpful: e.g. ">" -> "$gt"
        return PY2MONGO_OPS.get(v.strip(), v) if isinstance(v, str) else v

    def __repr__(self) -> str:
        metric = f"{self.agg.value}({self.name})" if self.agg else self.name
        op = MONGO2PY_OPS.get(self.cmp, self.cmp)
        return repr(rf"{metric} {op} {self.threshold}")

    @override
    def __rich_repr__(self) -> RichReprResult:  # type: ignore[override]
        yield None, repr(self)


class MetricChangeFilter(BaseMetricFilter):  # from `RunMetricChangeFilter`
    # FIXME:
    # - `prior_window` should be optional and default to `window` if not provided.
    # - implement declarative syntax for `MetricChangeFilter` similar to `MetricThresholdFilter`.
    # - split this into tagged union of relative/absolute change filters.

    name: str
    agg: Annotated[Optional[Agg], Field(alias="agg_op")] = None

    # FIXME: Set the `prior_window` to `window` if it's not provided, for convenience.
    window: Annotated[PositiveInt, Field(alias="current_window_size")]
    prior_window: Annotated[PositiveInt, Field(alias="prior_window_size")]
    """Size of the preceding window over which the metric is aggregated."""

    # NOTE: `cmp_op` isn't a field here.  In the backend, it's effectively `cmp_op` = "$gte"

    change_type: Annotated[ChangeType, Field(alias="change_type")]
    change_direction: Annotated[ChangeDirection, Field(alias="change_dir")]

    threshold: Annotated[Union[StrictInt, StrictFloat], Field(alias="change_amount")]


class BaseMetricOperand(GQLBase, extra="forbid"):
    def gt(self, other: int | float) -> MetricThresholdFilter:
        """Implements `MetricValueOperand > threshold` -> `MetricThreshold`."""
        return MetricThresholdFilter(**dict(self), cmp="$gt", threshold=other)

    def lt(self, other: int | float) -> MetricThresholdFilter:
        """Implements `MetricValueOperand < threshold` -> `MetricThreshold`."""
        return MetricThresholdFilter(**dict(self), cmp="$lt", threshold=other)

    def gte(self, other: int | float) -> MetricThresholdFilter:
        """Implements `MetricValueOperand >= threshold` -> `MetricThreshold`."""
        return MetricThresholdFilter(**dict(self), cmp="$gte", threshold=other)

    def lte(self, other: int | float) -> MetricThresholdFilter:
        """Implements `MetricValueOperand <= threshold` -> `MetricThreshold`."""
        return MetricThresholdFilter(**dict(self), cmp="$lte", threshold=other)

    __gt__ = gt
    __lt__ = lt
    __ge__ = gte
    __le__ = lte


class MetricVal(BaseMetricOperand):
    """Represents a single metric value when defining a metric filter."""

    name: str

    # Allow users to convert this single-value metric into an aggregated metric expression.
    def max(self, window: int) -> MetricAgg:
        return MetricAgg(name=self.name, agg=Agg.MAX, window=window)

    def min(self, window: int) -> MetricAgg:
        return MetricAgg(name=self.name, agg=Agg.MIN, window=window)

    def average(self, window: int) -> MetricAgg:
        return MetricAgg(name=self.name, agg=Agg.AVERAGE, window=window)

    # Aliased method for users familiar with e.g. torch/tf/numpy/pandas/polars/etc.
    def mean(self, window: int) -> MetricAgg:
        return self.average(window=window)


class MetricAgg(BaseMetricOperand):
    """Represents an aggregated metric value when defining a metric filter."""

    name: str
    agg: Optional[Agg] = Field(default=None, alias="agg_op")
    window: PositiveInt = Field(default=1, alias="window_size")
