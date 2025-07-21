from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Final, Literal, Optional, Union, overload

from pydantic import (
    Field,
    PositiveFloat,
    PositiveInt,
    StrictFloat,
    StrictInt,
    field_validator,
)
from typing_extensions import Annotated, TypeAlias, override

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

# Type hint for positive numbers (int or float)
PosNum: TypeAlias = Union[PositiveInt, PositiveFloat]


class Agg(LenientStrEnum):  # from: Aggregation
    """Supported run metric aggregation operations."""

    MAX = "MAX"
    MIN = "MIN"
    AVERAGE = "AVERAGE"

    # Shorter aliases for convenience
    AVG = AVERAGE


class ChangeType(LenientStrEnum):  # from: RunMetricChangeType
    """Describes the metric change as absolute (arithmetic difference) or relative (decimal percentage)."""

    ABSOLUTE = "ABSOLUTE"
    RELATIVE = "RELATIVE"

    # Shorter aliases for convenience
    ABS = ABSOLUTE
    REL = RELATIVE


class ChangeDir(LenientStrEnum):  # from: RunMetricChangeDirection
    """Describes the direction of the metric change."""

    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    ANY = "ANY"

    # Shorter aliases for convenience
    INC = INCREASE
    DEC = DECREASE


class BaseMetricFilter(GQLBase, ABC, extra="forbid"):
    name: str
    """Name of the observed metric."""

    agg: Optional[Agg]
    """Aggregate operation, if any, to apply over the window size."""

    window: PositiveInt
    """Size of the window over which the metric is aggregated (ignored if `agg is None`)."""

    # ------------------------------------------------------------------------------
    cmp: Optional[str]
    """Comparison between the metric expression (left) vs. the threshold or target value (right)."""

    # ------------------------------------------------------------------------------
    threshold: Union[StrictInt, StrictFloat]
    """Threshold value to compare against."""

    def __and__(self, other: Any) -> RunMetricFilter:
        """Implements `(metric_filter & run_filter) -> RunMetricFilter`."""
        from wandb.automations.events import RunMetricFilter

        if isinstance(run_filter := other, (BaseOp, FilterExpr)):
            # Assume `other` is a run filter, and we are building a RunMetricEvent.
            # For the metric filter, delegate to the inner validator(s) to further wrap/nest as appropriate.
            return RunMetricFilter(run=run_filter, metric=self)
        return NotImplemented

    def __rand__(self, other: BaseOp | FilterExpr) -> RunMetricFilter:
        """Ensures `&` is commutative: `(run_filter & metric_filter) == (metric_filter & run_filter)`."""
        return self.__and__(other)

    @abstractmethod
    def __repr__(self) -> str:
        """The text representation of the metric filter."""
        raise NotImplementedError

    @override
    def __rich_repr__(self) -> RichReprResult:
        """The representation of the metric filter when using `rich` for pretty-printing."""
        # See: https://rich.readthedocs.io/en/stable/pretty.html#rich-repr-protocol
        yield None, repr(self)


class MetricThresholdFilter(BaseMetricFilter):  # from: RunMetricThresholdFilter
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


class MetricChangeFilter(BaseMetricFilter):  # from: RunMetricChangeFilter
    """Defines a filter that compares a change in a run metric against a user-defined threshold.

    The change is calculated over "tumbling" windows, i.e. the difference
    between the current window and the non-overlapping prior window.
    """

    name: str
    agg: Annotated[Optional[Agg], Field(alias="agg_op")] = None
    window: Annotated[PositiveInt, Field(alias="current_window_size")] = 1

    # `prior_window` is only for `RUN_METRIC_CHANGE` events
    prior_window: Annotated[
        PositiveInt,
        # By default, set `window -> prior_window` if the latter wasn't provided.
        Field(alias="prior_window_size", default_factory=lambda data: data["window"]),
    ]
    """Size of the prior window over which the metric is aggregated (ignored if `agg is None`).

    If omitted, defaults to the size of the current window.
    """

    # ------------------------------------------------------------------------------
    # NOTE:
    # - The "comparison" operator isn't actually part of the backend schema,
    #   but it's defined here for consistency -- and ignored otherwise.
    # - In the backend, it's effectively "$gte" or "$lte", depending on the sign
    #   (change_dir), though again, this is not explicit in the schema.
    cmp: Annotated[None, Field(frozen=True, exclude=True, repr=False)] = None
    """Ignored."""

    # ------------------------------------------------------------------------------
    change_type: Annotated[ChangeType, Field(alias="change_type")]
    change_dir: Annotated[ChangeDir, Field(alias="change_dir")]
    threshold: Annotated[PosNum, Field(alias="change_amount")]

    def __repr__(self) -> str:
        metric = f"{self.agg.value}({self.name})" if self.agg else self.name
        verb = (
            "changes"
            if (self.change_dir is ChangeDir.ANY)
            else f"{self.change_dir.value.lower()}s"
        )

        fmt_spec = ".2%" if (self.change_type is ChangeType.REL) else ""
        amt = f"{self.threshold:{fmt_spec}}"
        return repr(rf"{metric} {verb} {amt}")


class BaseMetricOperand(GQLBase, extra="forbid"):
    def gt(self, value: int | float, /) -> MetricThresholdFilter:
        """Defines a `MetricThresholdFilter` that observes for `metric_expr > threshold`."""
        return self > value

    def lt(self, value: int | float, /) -> MetricThresholdFilter:
        """Defines a `MetricThresholdFilter` that observes for `metric_expr < threshold`."""
        return self < value

    def gte(self, value: int | float, /) -> MetricThresholdFilter:
        """Defines a `MetricThresholdFilter` that observes for `metric_expr >= threshold`."""
        return self >= value

    def lte(self, value: int | float, /) -> MetricThresholdFilter:
        """Defines a `MetricThresholdFilter` that observes for `metric_expr <= threshold`."""
        return self <= value

    # Overloads to implement:
    # - `(metric_operand > threshold) -> MetricThresholdFilter`
    # - `(metric_operand < threshold) -> MetricThresholdFilter`
    # - `(metric_operand >= threshold) -> MetricThresholdFilter`
    # - `(metric_operand <= threshold) -> MetricThresholdFilter`
    def __gt__(self, other: Any) -> MetricThresholdFilter:
        if isinstance(other, (int, float)):
            return MetricThresholdFilter(**dict(self), cmp="$gt", threshold=other)
        return NotImplemented

    def __lt__(self, other: Any) -> MetricThresholdFilter:
        if isinstance(other, (int, float)):
            return MetricThresholdFilter(**dict(self), cmp="$lt", threshold=other)
        return NotImplemented

    def __ge__(self, other: Any) -> MetricThresholdFilter:
        if isinstance(other, (int, float)):
            return MetricThresholdFilter(**dict(self), cmp="$gte", threshold=other)
        return NotImplemented

    def __le__(self, other: Any) -> MetricThresholdFilter:
        if isinstance(other, (int, float)):
            return MetricThresholdFilter(**dict(self), cmp="$lte", threshold=other)
        return NotImplemented

    @overload
    def changes_by(self, *, diff: PosNum, frac: None) -> MetricChangeFilter: ...
    @overload
    def changes_by(self, *, diff: None, frac: PosNum) -> MetricChangeFilter: ...
    @overload  # NOTE: This overload is for internal use only.
    def changes_by(
        self, *, diff: PosNum | None, frac: PosNum | None, _dir: ChangeDir
    ) -> MetricChangeFilter: ...
    def changes_by(
        self,
        *,
        diff: PosNum | None = None,
        frac: PosNum | None = None,
        _dir: ChangeDir = ChangeDir.ANY,
    ) -> MetricChangeFilter:
        """Defines a filter that observes for any change (increase OR decrease) in a run metric.

        Exactly one of the keyword arguments `frac` or `diff` must be provided.

        Args:
            diff:
                If given, the arithmetic difference that must be observed
                in the metric.  Must be a positive number.
            frac:
                If given, the fractional (relative) change that must be observed
                in the metric.  Must be a positive number.  E.g. `frac=0.1`
                denotes a 10% relative increase OR decrease.
        """
        # Enforce mutually exclusive keyword args
        if (frac is None) is (diff is None):
            raise ValueError("Must provide exactly one of `frac` or `diff`")

        # Enforce positive values
        if (frac is not None) and (frac <= 0):
            raise ValueError(f"Expected positive quantity, got: {frac=}")
        if (diff is not None) and (diff <= 0):
            raise ValueError(f"Expected positive quantity, got: {diff=}")

        if diff is None:
            change_kws = dict(change_type=ChangeType.REL, threshold=frac)
            return MetricChangeFilter(**dict(self), change_dir=_dir, **change_kws)
        else:
            change_kws = dict(change_type=ChangeType.ABS, threshold=diff)
            return MetricChangeFilter(**dict(self), change_dir=_dir, **change_kws)

    @overload
    def increases_by(self, *, diff: PosNum, frac: None) -> MetricChangeFilter: ...
    @overload
    def increases_by(self, *, diff: None, frac: PosNum) -> MetricChangeFilter: ...
    def increases_by(
        self, *, diff: PosNum | None = None, frac: PosNum | None = None
    ) -> MetricChangeFilter:
        """Defines a filter that observes for an increase in the numerical value of a run metric.

        Arguments are the same as for `.changes_by()`.
        """
        return self.changes_by(diff=diff, frac=frac, _dir=ChangeDir.INC)

    @overload
    def decreases_by(self, *, diff: PosNum, frac: None) -> MetricChangeFilter: ...
    @overload
    def decreases_by(self, *, diff: None, frac: PosNum) -> MetricChangeFilter: ...
    def decreases_by(
        self, *, diff: PosNum | None = None, frac: PosNum | None = None
    ) -> MetricChangeFilter:
        """Defines a filter that observes for a decrease in the numerical value of a run metric.

        Arguments are the same as for `.changes_by()`.
        """
        return self.changes_by(diff=diff, frac=frac, _dir=ChangeDir.DEC)


class MetricVal(BaseMetricOperand):
    """Represents a single, unaggregated metric value when defining a metric filter."""

    name: str

    # Allow users to convert this single-value metric into an aggregated metric expression.
    def max(self, window: int) -> MetricAgg:
        return MetricAgg(name=self.name, agg=Agg.MAX, window=window)

    def min(self, window: int) -> MetricAgg:
        return MetricAgg(name=self.name, agg=Agg.MIN, window=window)

    def avg(self, window: int) -> MetricAgg:
        return MetricAgg(name=self.name, agg=Agg.AVG, window=window)

    # Aliased method for users familiar with e.g. torch/tf/numpy/pandas/polars/etc.
    def mean(self, window: int) -> MetricAgg:
        return self.avg(window=window)


class MetricAgg(BaseMetricOperand):
    """Represents an aggregated metric value when defining a metric filter."""

    name: str
    agg: Annotated[Agg, Field(alias="agg_op")]
    window: Annotated[PositiveInt, Field(alias="window_size")]
