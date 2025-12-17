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
    """Describes the type of metric change as absolute or relative.

    ABSOLUTE: The arithmetic difference between the current vs. prior values.
    RELATIVE: The percentage change between the current vs. prior values.
    """

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
    """Size of the metric aggregation window (ignored if `agg` is ``None``)."""

    # ------------------------------------------------------------------------------
    cmp: Optional[str]
    """Comparison operator between the metric expression (left) vs. the threshold or target (right)."""  # noqa: W505

    # ------------------------------------------------------------------------------
    threshold: Union[StrictInt, StrictFloat]
    """Threshold value to compare against."""

    def __and__(self, other: Any) -> RunMetricFilter:
        """Returns `(metric_filter & run_filter)` as a `RunMetricFilter`."""
        from wandb.automations.events import RunMetricFilter

        if isinstance(run_filter := other, (BaseOp, FilterExpr)):
            # Treat `other` as a run filter and build a RunMetricEvent. Let the
            # metric filter validators wrap or nest as appropriate.
            return RunMetricFilter(run=run_filter, metric=self)
        return NotImplemented

    def __rand__(self, other: BaseOp | FilterExpr) -> RunMetricFilter:
        """Ensures `&` is commutative for run and metric filters.

        I.e. `(run_filter & metric_filter) == (metric_filter & run_filter)`.
        """
        return self.__and__(other)

    @abstractmethod
    def __repr__(self) -> str:
        """Returns the text representation of the metric filter."""
        raise NotImplementedError

    @override
    def __rich_repr__(self) -> RichReprResult:
        """Returns the `rich` pretty-print representation of the metric filter."""
        # See: https://rich.readthedocs.io/en/stable/pretty.html#rich-repr-protocol
        yield None, repr(self)


class MetricThresholdFilter(BaseMetricFilter):  # from: RunMetricThresholdFilter
    """Filter that compares an **absolute** metric value against a user-defined threshold.

    The value may be a single value or an aggregated result over a window of
    multiple values.
    """

    name: str
    agg: Annotated[Optional[Agg], Field(alias="agg_op")] = None
    window: Annotated[PositiveInt, Field(alias="window_size")] = 1

    cmp: Annotated[Literal["$gte", "$gt", "$lt", "$lte"], Field(alias="cmp_op")]
    """Comparison operator between the metric value (left) vs. the threshold (right)."""

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
    """Filter that compares a **change** in a metric value to a user-defined threshold.

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
    """Size of the "prior" metric aggregation window (ignored if `agg` is ``None``).

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
    change_type: ChangeType
    change_dir: ChangeDir
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


class BaseMetricOperand(GQLBase, ABC, extra="forbid"):
    def gt(self, value: int | float, /) -> MetricThresholdFilter:
        """Returns a filter that watches for `metric_expr > threshold`."""
        return self > value

    def lt(self, value: int | float, /) -> MetricThresholdFilter:
        """Returns a filter that watches for `metric_expr < threshold`."""
        return self < value

    def gte(self, value: int | float, /) -> MetricThresholdFilter:
        """Returns a filter that watches for `metric_expr >= threshold`."""
        return self >= value

    def lte(self, value: int | float, /) -> MetricThresholdFilter:
        """Returns a filter that watches for `metric_expr <= threshold`."""
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
        """Returns a filter that watches for a numerical increase OR decrease in a metric.

        Exactly one of `frac` or `diff` must be provided.

        Args:
            diff: If given, arithmetic difference that must be observed in the metric.
                Must be positive.
            frac: If given, fractional (relative) change that must be observed in the
                metric. Must be positive. For example, `frac=0.1` denotes a 10% relative
                increase or decrease.
        """
        if (
            # Enforce mutually exclusive keyword args
            ((frac is None) and (diff is None))
            or ((frac is not None) and (diff is not None))
        ):
            raise ValueError("Must provide exactly one of `frac` or `diff`")

        # Enforce positive values
        if (frac is not None) and (frac <= 0):
            raise ValueError(f"Expected positive threshold, got: {frac=}")
        if (diff is not None) and (diff <= 0):
            raise ValueError(f"Expected positive threshold, got: {diff=}")

        if diff is None:
            kws = dict(change_dir=_dir, change_type=ChangeType.REL, threshold=frac)
        else:
            kws = dict(change_dir=_dir, change_type=ChangeType.ABS, threshold=diff)
        return MetricChangeFilter(**dict(self), **kws)

    @overload
    def increases_by(self, *, diff: PosNum, frac: None) -> MetricChangeFilter: ...

    @overload
    def increases_by(self, *, diff: None, frac: PosNum) -> MetricChangeFilter: ...

    def increases_by(
        self, *, diff: PosNum | None = None, frac: PosNum | None = None
    ) -> MetricChangeFilter:
        """Returns a filter that watches for a numerical increase in a metric.

        Arguments mirror those of `.changes_by()`.
        """
        return self.changes_by(diff=diff, frac=frac, _dir=ChangeDir.INC)

    @overload
    def decreases_by(self, *, diff: PosNum, frac: None) -> MetricChangeFilter: ...

    @overload
    def decreases_by(self, *, diff: None, frac: PosNum) -> MetricChangeFilter: ...

    def decreases_by(
        self, *, diff: PosNum | None = None, frac: PosNum | None = None
    ) -> MetricChangeFilter:
        """Returns a filter that watches for a numerical decrease in a metric.

        Arguments mirror those of `.changes_by()`.
        """
        return self.changes_by(diff=diff, frac=frac, _dir=ChangeDir.DEC)


class MetricVal(BaseMetricOperand):
    """Represents a single metric value when defining metric event filters."""

    name: str

    # Allow conversion of a single-value metric into an aggregated expression.
    def max(self, window: int) -> MetricAgg:
        return MetricAgg(name=self.name, agg=Agg.MAX, window=window)

    def min(self, window: int) -> MetricAgg:
        return MetricAgg(name=self.name, agg=Agg.MIN, window=window)

    def avg(self, window: int) -> MetricAgg:
        return MetricAgg(name=self.name, agg=Agg.AVG, window=window)

    # Aliased method for users familiar with e.g. torch/tf/numpy/pandas/polars/etc.
    def mean(self, window: int) -> MetricAgg:
        return self.avg(window=window)

    def zscore(self, window: int) -> ZScoreMetricOperand:
        """Returns a z-score metric builder for fluent filter construction.

        Use with comparison operators to create z-score filters:
        - `metric.zscore(30) > 3` - detects z-score increases above 3 std devs
        - `metric.zscore(30) < -3` - detects z-score decreases below -3 std devs
        - `metric.zscore(30).abs() > 3` - detects abs z-score deviations above 3 std devs

        Note:
        - The `>=` operator behaves the same as `>`, and `<=` behaves the same as `<`.
        """
        return ZScoreMetricOperand(name=self.name, window=window)


class MetricAgg(BaseMetricOperand):
    """Represents an aggregated metric value when defining metric event filters."""

    name: str
    agg: Annotated[Agg, Field(alias="agg_op")]
    window: Annotated[PositiveInt, Field(alias="window_size")]


class ZScoreMetricOperand(GQLBase, extra="forbid"):
    """Helper class to build z-score metric filters with comparison operators.

    This class enables fluent construction of z-score filters using Python
    comparison operators (>, <, >=, <=) and the builtin abs() function.

    Note: When defining a z-score threshold, the `>` and `>=` operators are
    interchangeable, as are the `<=` and `<` operators, since the z-score defines
    a threshold on a continuous value. At runtime, the filter is evaluated
    using the inclusive operators (`>=` or `<=`).
    """

    name: str
    """Name of the metric to monitor."""

    window: PositiveInt
    """Size of the window to calculate the metric mean and standard deviation over."""

    is_absolute: bool = Field(default=False, repr=False)
    """Whether to check the absolute value of the z-score (ignoring direction)."""

    def lt(self, value: int | float, /) -> MetricZScoreFilter:
        """Returns a filter that watches for `zscore(metric) < -threshold`.

        Args:
            value: The z-score threshold value to compare against.
                   The absolute value is used as the threshold.
        """
        if self.is_absolute:
            raise ValueError("Cannot use absolute z-score with < operator")

        if value >= 0:
            raise ValueError("Negative z-score threshold required")

        return MetricZScoreFilter(
            name=self.name,
            window=self.window,
            change_dir=ChangeDir.DECREASE,
            threshold=abs(value),
        )

    def __lt__(self, value: int | float, /) -> MetricZScoreFilter:
        return self.lt(value)

    def __le__(self, value: int | float, /) -> MetricZScoreFilter:
        """Alias for `<` operator - behaves identically to `__lt__`.

        Returns a filter that watches for `zscore(metric) < -threshold`.
        Note: `<=` and `<` are treated as equivalent for z-score filters.
        """
        return self.lt(value)

    def gt(self, value: int | float, /) -> MetricZScoreFilter:
        """Returns a filter that watches for `zscore(metric) > threshold`.

        If `is_absolute` is True, watches for `abs(zscore(metric)) > threshold`.

        Args:
            value: The z-score threshold value to compare against.
                   The absolute value is used as the threshold.
        """
        if value <= 0:
            raise ValueError(f"Expected positive threshold, got: {value=}")

        return MetricZScoreFilter(
            name=self.name,
            window=self.window,
            change_dir=ChangeDir.ANY if self.is_absolute else ChangeDir.INCREASE,
            threshold=abs(value),
        )

    def __gt__(self, value: int | float, /) -> MetricZScoreFilter:
        return self.gt(value)

    def __ge__(self, value: int | float, /) -> MetricZScoreFilter:
        """Alias for `>` operator - behaves identically to `__gt__`.

        Returns a filter that watches for `zscore(metric) > threshold`.
        If `is_absolute` is True, watches for `abs(zscore(metric)) > threshold`.
        Note: `>=` and `>` are treated as equivalent for z-score filters.
        """
        return self.gt(value)

    def __abs__(self) -> ZScoreMetricOperand:
        """Returns a z-score filter that checks the absolute value.

        This allows watching for z-score deviations in either direction.
        Use with comparison operators: `abs(metric.zscore(window)) > threshold`.
        """
        return self.model_copy(update={"is_absolute": True})

    def abs(self) -> ZScoreMetricOperand:
        """Returns a z-score filter that checks the absolute value.

        Alias for `__abs__()` that can be called as a method.
        Allows using either `abs(zscore)` or `zscore.abs()`.
        """
        return self.__abs__()


class MetricZScoreFilter(GQLBase, extra="forbid"):
    """Filter that compares a metric's z-score against a user-defined threshold."""

    name: str
    """Name of the observed metric."""

    window: Annotated[PositiveInt, Field(alias="window_size")] = 30
    """Size of the window to calculate the metric mean and standard deviation over."""

    threshold: PosNum = 3.0
    """Threshold for the z-score."""

    change_dir: ChangeDir = ChangeDir.ANY
    """Direction of the z-score change to watch for."""

    def __and__(self, other: Any) -> RunMetricFilter:
        """Returns `(metric_filter & run_filter)` as a `RunMetricFilter`."""
        from wandb.automations.events import RunMetricFilter

        if isinstance(run_filter := other, (BaseOp, FilterExpr)):
            # Treat `other` as a run filter and build a RunMetricEvent. Let the
            # metric filter validators wrap or nest as appropriate.
            return RunMetricFilter(run=run_filter, metric=self)
        return NotImplemented

    def __rand__(self, other: BaseOp | FilterExpr) -> RunMetricFilter:
        """Ensures `&` is commutative for run and metric filters.

        I.e. `(run_filter & metric_filter) == (metric_filter & run_filter)`.
        """
        return self.__and__(other)

    def __repr__(self) -> str:
        if self.change_dir is ChangeDir.ANY:
            return repr(rf"abs(zscore({self.name!r})) > {self.threshold}")
        elif self.change_dir is ChangeDir.DECREASE:
            return repr(rf"zscore({self.name!r}) < -{self.threshold}")
        else:  # ChangeDir.INCREASE
            return repr(rf"zscore({self.name!r}) > +{self.threshold}")

    @override
    def __rich_repr__(self) -> RichReprResult:
        """Returns the `rich` pretty-print representation of the metric filter."""
        # See: https://rich.readthedocs.io/en/stable/pretty.html#rich-repr-protocol
        yield None, repr(self)
