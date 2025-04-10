# ruff: noqa: UP007

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Final, Literal, Optional, Union, overload

from pydantic import Field, PositiveInt, StrictFloat, StrictInt, field_validator
from typing_extensions import Self, override

from wandb._pydantic.base import Base, GQLBase

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


class Agg(str, Enum):  # from `Aggregation`
    """Supported run metric aggregation operations."""

    MAX = "MAX"
    MIN = "MIN"
    AVERAGE = "AVERAGE"


class ChangeType(str, Enum):  # from `RunMetricChangeType`
    """Describes the metric change as absolute (arithmetic difference) or relative (decimal percentage)."""

    ABSOLUTE = "ABSOLUTE"
    RELATIVE = "RELATIVE"


class ChangeDirection(str, Enum):  # from `RunMetricChangeDirection`
    """Describes the direction of the metric change."""

    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    ANY = "ANY"


class _BaseMetricFilter(GQLBase):
    name: str
    """Name of the observed metric."""

    agg: Optional[Agg]
    """Aggregation operation, if any, to apply over the window size."""

    window: PositiveInt
    """Size of the window over which the metric is aggregated."""

    # ------------------------------------------------------------------------------

    threshold: Union[StrictInt, StrictFloat]
    """Threshold value to compare against."""

    @field_validator("agg", mode="before")
    @classmethod
    def _validate_agg(cls, v: Any) -> Any:
        # Be helpful: e.g. "min" -> "MIN"
        return v.strip().upper() if isinstance(v, str) else v

    @overload
    def __and__(self, other: BaseOp | FilterExpr) -> RunMetricFilter: ...
    @overload
    def __and__(self, other: Any) -> Any: ...
    def __and__(self, other: BaseOp | FilterExpr | Any) -> RunMetricFilter | Any:
        """Supports syntactic sugar for defining a triggering RunMetricEvent from `run_metric_filter & run_filter`."""
        from wandb.automations.events import RunMetricFilter, _InnerRunMetricFilter

        if isinstance(run_filter := other, (BaseOp, FilterExpr)):
            # Assume `other` is a run filter, and we are building a RunMetricEvent.
            # For the metric filter, delegate to the inner validator(s) to further wrap/nest as appropriate.
            metric_filter = _InnerRunMetricFilter.model_validate(self)
            return RunMetricFilter(
                run_metric_filter=metric_filter, run_filter=run_filter
            )
        return other.__and__(self)  # Try switching the order of operands


class MetricThresholdFilter(_BaseMetricFilter):  # from `RunMetricThresholdFilter`
    """For run events, defines a metric filter comparing a metric against a user-defined threshold value."""

    name: str
    agg: Optional[Agg] = Field(default=None, alias="agg_op")
    window: PositiveInt = Field(default=1, alias="window_size")

    cmp: Literal["$gte", "$gt", "$lt", "$lte"] = Field(alias="cmp_op")
    """Comparison operator used to compare the metric value (left) vs. the threshold value (right)."""

    threshold: Union[StrictInt, StrictFloat]

    @field_validator("cmp", mode="before")
    @classmethod
    def _validate_cmp(cls, v: Any) -> Any:
        # Be helpful: e.g. ">" -> "$gt"
        return PY2MONGO_OPS.get(v.strip(), v) if isinstance(v, str) else v

    def __repr__(self) -> str:
        metric = f"{self.agg.value}({self.name})" if self.agg else self.name
        op = MONGO2PY_OPS.get(self.cmp, self.cmp)
        expr = rf"{metric} {op} {self.threshold}"
        return repr(expr)

    @override
    def __rich_repr__(self) -> RichReprResult:  # type: ignore[override]
        yield None, repr(self)


class MetricChangeFilter(_BaseMetricFilter):  # from `RunMetricChangeFilter`
    # FIXME:
    # - `prior_window` should be optional and default to `window` if not provided.
    # - implement declarative syntax for `MetricChangeFilter` similar to `MetricThresholdFilter`.
    # - split this into tagged union of relative/absolute change filters.

    name: str
    agg: Optional[Agg] = Field(default=None, alias="agg_op")

    # FIXME: Set the `prior_window` to `window` if it's not provided, for convenience.
    window: PositiveInt = Field(alias="current_window_size")
    prior_window: PositiveInt = Field(alias="prior_window_size")
    """Size of the preceding window over which the metric is aggregated."""

    # NOTE: `cmp_op` isn't a field here.  In the backend, it's effectively `cmp_op` = "$gte"

    change_type: ChangeType = Field(alias="change_type")
    change_direction: ChangeDirection = Field(alias="change_dir")

    threshold: Union[StrictInt, StrictFloat] = Field(alias="change_amount")


class MetricOperand(Base):
    name: str
    agg: Optional[Agg] = Field(default=None, alias="agg_op")
    window: PositiveInt = Field(default=1, alias="window_size")

    def _agg(self, op: Agg, window: int) -> Self:
        if self.agg is None:  # Prevent overwriting an existing aggregation operator
            return self.model_copy(update={"agg": op, "window": window})
        raise ValueError(f"Aggregation operator already set as: {self.agg!r}")

    def max(self, window: int) -> Self:
        return self._agg(Agg.MAX, window)

    def min(self, window: int) -> Self:
        return self._agg(Agg.MIN, window)

    def average(self, window: int) -> Self:
        return self._agg(Agg.AVERAGE, window)

    # Aliased method for users familiar with e.g. torch/tf/numpy/pandas/polars/etc.
    def mean(self, window: int) -> Self:
        return self.average(window=window)

    def gt(self, other: int | float) -> MetricThresholdFilter:
        return MetricThresholdFilter(**dict(self), cmp="$gt", threshold=other)

    def lt(self, other: int | float) -> MetricThresholdFilter:
        return MetricThresholdFilter(**dict(self), cmp="$lt", threshold=other)

    def gte(self, other: int | float) -> MetricThresholdFilter:
        return MetricThresholdFilter(**dict(self), cmp="$gte", threshold=other)

    def lte(self, other: int | float) -> MetricThresholdFilter:
        return MetricThresholdFilter(**dict(self), cmp="$lte", threshold=other)

    __gt__ = gt
    __lt__ = lt
    __ge__ = gte
    __le__ = lte
