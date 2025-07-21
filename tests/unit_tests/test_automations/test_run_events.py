from __future__ import annotations

import json

from hypothesis import given
from hypothesis.strategies import DrawFn, SearchStrategy, composite, sampled_from
from pytest import raises
from wandb.automations import MetricChangeFilter, MetricThresholdFilter, RunEvent
from wandb.automations._filters.run_metrics import Agg, MetricAgg, MetricVal

from ._strategies import (
    aggs,
    cmp_keys,
    ints_or_floats,
    metric_change_filters,
    metric_names,
    nonpos_numbers,
    pos_numbers,
    window_sizes,
)


@composite
def metric_operands(
    draw: DrawFn,
    names: SearchStrategy[str] = metric_names,
    windows: SearchStrategy[int] = window_sizes,
) -> SearchStrategy[MetricVal | MetricAgg]:
    """Generate single-value and/or aggregated metric operands.

    Think of this as the "left-hand side" of a metric threshold filtering condition.
    """
    name, window = draw(names), draw(windows)

    all_metric_operands = (
        RunEvent.metric(name),
        RunEvent.metric(name).avg(window),
        RunEvent.metric(name).mean(window),
        RunEvent.metric(name).min(window),
        RunEvent.metric(name).max(window),
    )
    return draw(sampled_from(all_metric_operands))


@given(
    name=metric_names,
    window=window_sizes,
    agg=aggs,
    cmp=cmp_keys,
    threshold=ints_or_floats,
)
def test_metric_threshold_filter_serialization(
    name: str, window: int, agg: str | None, cmp: str, threshold: int | float
):
    """Check that a normally-instantiated `MetricThresholdFilter` produces the expected JSON-serializable dict."""
    metric_filter = MetricThresholdFilter(
        name=name, window=window, agg=agg, cmp=cmp, threshold=threshold
    )

    expected_agg = None if (agg is None) else Agg(agg).value
    expected_dict = {
        "name": name,
        "window_size": window,
        "agg_op": expected_agg,
        "cmp_op": cmp,
        "threshold": threshold,
    }

    assert metric_filter.model_dump() == expected_dict
    assert json.loads(metric_filter.model_dump_json()) == expected_dict


@given(
    metric=metric_operands(),
    threshold=ints_or_floats,
)
def test_metric_threshold_binop_vs_method_is_equivalent(
    metric: MetricVal | MetricAgg, threshold: float
):
    """Metric filters declared via (a) binary comparison operators vs (b) chained method calls are equivalent.

    E.g. `metric > threshold` should do the same thing as `metric.gt(threshold)`.
    """
    assert isinstance(metric, (MetricVal, MetricAgg))

    # Check that the (serializable) data is equivalent
    assert (metric > threshold).model_dump() == metric.gt(threshold).model_dump()
    assert (metric >= threshold).model_dump() == metric.gte(threshold).model_dump()
    assert (metric < threshold).model_dump() == metric.lt(threshold).model_dump()
    assert (metric <= threshold).model_dump() == metric.lte(threshold).model_dump()

    # Check string representations are identical
    assert repr(metric > threshold) == repr(metric.gt(threshold))
    assert repr(metric >= threshold) == repr(metric.gte(threshold))
    assert repr(metric < threshold) == repr(metric.lt(threshold))
    assert repr(metric <= threshold) == repr(metric.lte(threshold))


def test_run_metric_threshold_cannot_be_aggregated_twice():
    """Check that run metric thresholds forbid multiple aggregations."""
    with raises(AttributeError):
        RunEvent.metric("my-metric").avg(5).average(10)
    with raises(AttributeError):
        RunEvent.metric("my-metric").avg(10).max(5)


@given(
    metric=metric_operands(),
    threshold=ints_or_floats,
)
def test_metric_threshold_filter_repr(metric: MetricVal | MetricAgg, threshold: float):
    """Check that a metric threshold filter has the expected human-readable representation."""
    # Determine the expected left- and right-hand sides of the inequality
    if isinstance(metric, MetricVal):
        # Single-value metric operand (i.e. no aggregation)
        expected_lhs = metric.name
    elif isinstance(metric, MetricAgg):
        # Aggregated metric operand
        expected_lhs = f"{metric.agg.value}({metric.name})"
    else:
        raise TypeError(f"Unhandled metric operand type: {type(metric)}")

    # Check that the string representations are equivalent
    assert repr(metric.gt(threshold)) == repr(f"{expected_lhs} > {threshold}")
    assert repr(metric.gte(threshold)) == repr(f"{expected_lhs} >= {threshold}")
    assert repr(metric.lt(threshold)) == repr(f"{expected_lhs} < {threshold}")
    assert repr(metric.lte(threshold)) == repr(f"{expected_lhs} <= {threshold}")


@given(metric_filter=metric_change_filters())
def test_metric_change_filter_serialization(metric_filter: MetricChangeFilter):
    """Check that a normally-instantiated `MetricChangeFilter` produces the expected JSON-serializable dict."""
    expected_dict = {
        "name": metric_filter.name,
        "agg_op": agg.value if (agg := metric_filter.agg) else None,
        "current_window_size": metric_filter.window,
        "prior_window_size": metric_filter.prior_window,
        "change_dir": metric_filter.change_dir.value,
        "change_type": metric_filter.change_type.value,
        "change_amount": metric_filter.threshold,
    }

    assert metric_filter.model_dump() == expected_dict
    assert json.loads(metric_filter.model_dump_json()) == expected_dict


@given(
    metric_filter=metric_change_filters(
        prior_window=None,  # NOTE: `prior_window` deliberately omitted
    ),
)
def test_metric_change_filter_defaults_prior_window_to_current_window(
    metric_filter: MetricChangeFilter,
):
    """Check that if "prior_window" is omitted, it defaults to the current window size."""
    assert metric_filter.prior_window == metric_filter.window

    # For good measure, check both the model_dump() and model_dump_json() contents
    dict_ = metric_filter.model_dump()
    dict_from_json = json.loads(metric_filter.model_dump_json())

    assert dict_["prior_window_size"] == dict_["current_window_size"]
    assert dict_from_json["prior_window_size"] == dict_from_json["current_window_size"]


@given(
    metric=metric_operands(),
    delta=pos_numbers,
)
def test_metric_change_filter_repr(metric: MetricVal | MetricAgg, delta: float):
    """Check that a metric change filter has the expected human-readable representation."""
    # Determine the expected left- and right-hand sides of the inequality
    if isinstance(metric, MetricVal):
        # Single-value metric operand (i.e. no aggregation)
        expected_lhs = metric.name
    elif isinstance(metric, MetricAgg):
        # Aggregated metric operand
        expected_lhs = f"{metric.agg.value}({metric.name})"
    else:
        raise TypeError(f"Unhandled metric operand type: {type(metric)}")

    # Check that the string representations are equivalent
    metric_filter_repr = repr(metric.changes_by(frac=delta))
    assert metric_filter_repr == repr(f"{expected_lhs} changes {delta:.2%}")

    metric_filter_repr = repr(metric.changes_by(diff=delta))
    assert metric_filter_repr == repr(f"{expected_lhs} changes {delta}")

    metric_filter_repr = repr(metric.increases_by(frac=delta))
    assert metric_filter_repr == repr(f"{expected_lhs} increases {delta:.2%}")

    metric_filter_repr = repr(metric.increases_by(diff=delta))
    assert metric_filter_repr == repr(f"{expected_lhs} increases {delta}")

    metric_filter_repr = repr(metric.decreases_by(frac=delta))
    assert metric_filter_repr == repr(f"{expected_lhs} decreases {delta:.2%}")

    metric_filter_repr = repr(metric.decreases_by(diff=delta))
    assert metric_filter_repr == repr(f"{expected_lhs} decreases {delta}")


@given(
    name=metric_names,
    window=window_sizes,
    delta=pos_numbers,
)
def test_declarative_metric_change_filter_with_agg(
    name: str, window: int, delta: int | float
):
    """Check that declared `MetricChangeFilter` WITH an aggregate operation produces the expected JSONable dict."""
    # Expected JSON-serializable contents shared by all test cases here
    always_expected = {
        "name": name,
        "current_window_size": window,
        "prior_window_size": window,
        "change_amount": delta,
    }

    # AVERAGE, ANY direction, RELATIVE change
    metric_filter = RunEvent.metric(name).avg(window).changes_by(frac=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "agg_op": "AVERAGE",
        "change_dir": "ANY",
        "change_type": "RELATIVE",
        **always_expected,
    }

    # AVERAGE, ANY direction, ABSOLUTE change
    metric_filter = RunEvent.metric(name).avg(window).changes_by(diff=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "agg_op": "AVERAGE",
        "change_dir": "ANY",
        "change_type": "ABSOLUTE",
        **always_expected,
    }

    # MAX, INCREASE, RELATIVE change
    metric_filter = RunEvent.metric(name).max(window).increases_by(frac=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "agg_op": "MAX",
        "change_dir": "INCREASE",
        "change_type": "RELATIVE",
        **always_expected,
    }

    # MAX, DECREASE, ABSOLUTE change
    metric_filter = RunEvent.metric(name).max(window).increases_by(diff=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "agg_op": "MAX",
        "change_dir": "INCREASE",
        "change_type": "ABSOLUTE",
        **always_expected,
    }

    # MIN, INCREASE, RELATIVE change
    metric_filter = RunEvent.metric(name).min(window).increases_by(frac=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "agg_op": "MIN",
        "change_dir": "INCREASE",
        "change_type": "RELATIVE",
        **always_expected,
    }

    # MIN, DECREASE, ABSOLUTE change
    metric_filter = RunEvent.metric(name).min(window).decreases_by(diff=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "agg_op": "MIN",
        "change_dir": "DECREASE",
        "change_type": "ABSOLUTE",
        **always_expected,
    }


@given(
    name=metric_names,
    delta=pos_numbers,
)
def test_declarative_metric_change_filter_without_agg(name: str, delta: int | float):
    """Check that the declarative syntax for `MetricChangeFilter` produces the expected `MetricChangeFilter`."""
    # Expected items in ALL test cases here
    always_expected = {
        "name": name,
        "agg_op": None,
        "current_window_size": 1,
        "prior_window_size": 1,
        "change_amount": delta,
    }

    # Single-value, ANY direction, RELATIVE change
    metric_filter = RunEvent.metric(name).changes_by(frac=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "change_dir": "ANY",
        "change_type": "RELATIVE",
        **always_expected,
    }

    # Single-value, ANY direction, ABSOLUTE change
    metric_filter = RunEvent.metric(name).changes_by(diff=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "change_dir": "ANY",
        "change_type": "ABSOLUTE",
        **always_expected,
    }

    # Single-value, INCREASE, RELATIVE change
    metric_filter = RunEvent.metric(name).increases_by(frac=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "change_dir": "INCREASE",
        "change_type": "RELATIVE",
        **always_expected,
    }

    # Single-value, INCREASE, ABSOLUTE change
    metric_filter = RunEvent.metric(name).increases_by(diff=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "change_dir": "INCREASE",
        "change_type": "ABSOLUTE",
        **always_expected,
    }

    # Single-value, DECREASE, RELATIVE change
    metric_filter = RunEvent.metric(name).decreases_by(frac=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "change_dir": "DECREASE",
        "change_type": "RELATIVE",
        **always_expected,
    }

    # Single-value, DECREASE, ABSOLUTE change
    metric_filter = RunEvent.metric(name).decreases_by(diff=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "change_dir": "DECREASE",
        "change_type": "ABSOLUTE",
        **always_expected,
    }


@given(
    metric=metric_operands(),
    delta=pos_numbers,
)
def test_declarative_metric_change_filter_requires_exaclty_one_delta_keyword_arg(
    metric: MetricVal | MetricAgg, delta: int | float
):
    """Check that a `MetricChangeFilter` requires exactly one of `frac` or `diff`."""
    # Both keyword args at once is forbidden
    with raises(ValueError):
        metric.changes_by(frac=delta, diff=delta)
    with raises(ValueError):
        metric.increases_by(frac=delta, diff=delta)
    with raises(ValueError):
        metric.decreases_by(frac=delta, diff=delta)

    # ...so is 0 args
    with raises(ValueError):
        metric.changes_by()
    with raises(ValueError):
        metric.increases_by()
    with raises(ValueError):
        metric.decreases_by()

    # ... so is a positional arg, as it's too ambiguous
    with raises(TypeError):
        metric.changes_by(delta)
    with raises(TypeError):
        metric.increases_by(delta)
    with raises(TypeError):
        metric.decreases_by(delta)


@given(
    metric=metric_operands(),
    invalid_delta=nonpos_numbers,
)
def test_declarative_metric_change_filter_requires_positive_delta(
    metric: MetricVal | MetricAgg, invalid_delta: int | float
):
    """Check that a `MetricChangeFilter` only accepts a POSITIVE quantity for `frac` or `diff`."""
    with raises(ValueError):
        metric.changes_by(frac=invalid_delta)
    with raises(ValueError):
        metric.changes_by(diff=invalid_delta)
    with raises(ValueError):
        metric.increases_by(frac=invalid_delta)
    with raises(ValueError):
        metric.increases_by(diff=invalid_delta)
    with raises(ValueError):
        metric.decreases_by(frac=invalid_delta)
    with raises(ValueError):
        metric.decreases_by(diff=invalid_delta)
