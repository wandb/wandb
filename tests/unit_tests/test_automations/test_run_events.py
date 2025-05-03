from __future__ import annotations

import json
from typing import Iterable

from hypothesis import given
from hypothesis.strategies import SearchStrategy, floats, integers, none, one_of
from pytest import raises
from wandb.apis.public.projects import Project
from wandb.automations import EventType, OnRunMetric, RunEvent
from wandb.automations._filters.run_metrics import (
    Agg,
    BaseMetricOperand,
    ChangeDir,
    ChangeType,
    MetricChangeFilter,
    MetricThresholdFilter,
)

from ._strategies import (
    cmp_op_keys,
    ints_or_floats,
    metric_change_filters,
    printable_text,
    sample_with_randomcase,
    window_sizes,
)

# Valid "change_amount" values (i.e. `frac` or `diff`)
positive_amounts: SearchStrategy[int | float] = one_of(
    integers(min_value=1),
    floats(
        min_value=0,
        exclude_min=True,
        width=32,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
)

# Invalid "change_amount" values (i.e. `frac` or `diff`)
nonpositive_amounts: SearchStrategy[int | float] = one_of(
    integers(max_value=0),
    floats(
        max_value=0,
        width=32,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
)


@given(
    name=printable_text,
    window=window_sizes,
    agg=none() | sample_with_randomcase(Agg),
    cmp=cmp_op_keys,
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
    name=printable_text,
    window=window_sizes,
    threshold=ints_or_floats,
)
def test_metric_threshold_filter_repr(name: str, window: int, threshold: float):
    """Check that a metric threshold filter has the expected human-readable representation."""
    metric_value_expr = RunEvent.metric(name)  # Single value

    # Expected left- and right-hand sides of the comparison
    lhs = f"{name}"
    rhs = f"{threshold}"

    assert repr(metric_value_expr.gt(threshold)) == repr(f"{lhs} > {rhs}")
    assert repr(metric_value_expr > threshold) == repr(f"{lhs} > {rhs}")

    assert repr(metric_value_expr.gte(threshold)) == repr(f"{lhs} >= {rhs}")
    assert repr(metric_value_expr >= threshold) == repr(f"{lhs} >= {rhs}")

    assert repr(metric_value_expr.lt(threshold)) == repr(f"{lhs} < {rhs}")
    assert repr(metric_value_expr < threshold) == repr(f"{lhs} < {rhs}")

    assert repr(metric_value_expr.lte(threshold)) == repr(f"{lhs} <= {rhs}")
    assert repr(metric_value_expr <= threshold) == repr(f"{lhs} <= {rhs}")

    # Aggregate expressions
    metric_agg_expressions = [
        (Agg.AVG, RunEvent.metric(name).average(window)),
        (Agg.AVG, RunEvent.metric(name).mean(window)),
        (Agg.MIN, RunEvent.metric(name).min(window)),
        (Agg.MAX, RunEvent.metric(name).max(window)),
    ]

    for agg, metric_agg_expr in metric_agg_expressions:
        # Expected left- and right-hand sides of the comparison
        lhs = f"{agg.value}({name})"
        rhs = f"{threshold}"

        assert repr(metric_agg_expr.gt(threshold)) == repr(f"{lhs} > {rhs}")
        assert repr(metric_agg_expr > threshold) == repr(f"{lhs} > {rhs}")

        assert repr(metric_agg_expr.gte(threshold)) == repr(f"{lhs} >= {rhs}")
        assert repr(metric_agg_expr >= threshold) == repr(f"{lhs} >= {rhs}")

        assert repr(metric_agg_expr.lt(threshold)) == repr(f"{lhs} < {rhs}")
        assert repr(metric_agg_expr < threshold) == repr(f"{lhs} < {rhs}")

        assert repr(metric_agg_expr.lte(threshold)) == repr(f"{lhs} <= {rhs}")
        assert repr(metric_agg_expr <= threshold) == repr(f"{lhs} <= {rhs}")


@given(
    metric_filter=metric_change_filters(
        name=printable_text,
        agg=none() | sample_with_randomcase(Agg),
        window=window_sizes,
        prior_window=window_sizes,
        threshold=positive_amounts,
        change_type=sample_with_randomcase(ChangeType),
        change_dir=sample_with_randomcase(ChangeDir),
    ),
)
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
        name=printable_text,
        agg=none() | sample_with_randomcase(Agg),
        window=window_sizes,
        # NOTE: prior_window deliberately omitted
        threshold=positive_amounts,
        change_type=sample_with_randomcase(ChangeType),
        change_dir=sample_with_randomcase(ChangeDir),
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
    name=printable_text,
    window=window_sizes,
    delta=positive_amounts,
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
    metric_filter = RunEvent.metric(name).average(window).changes_by(frac=delta)
    assert isinstance(metric_filter, MetricChangeFilter)
    assert metric_filter.model_dump() == {
        "agg_op": "AVERAGE",
        "change_dir": "ANY",
        "change_type": "RELATIVE",
        **always_expected,
    }

    # AVERAGE, ANY direction, ABSOLUTE change
    metric_filter = RunEvent.metric(name).average(window).changes_by(diff=delta)
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
    name=printable_text,
    delta=positive_amounts,
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
    name=printable_text,
    window=window_sizes,
    delta=positive_amounts,
)
def test_declarative_metric_change_filter_requires_exaclty_one_delta_keyword_arg(
    name: str, window: int, delta: int | float
):
    """Check that a `MetricChangeFilter` requires exactly one of `frac` or `diff`."""
    metric_operands: Iterable[BaseMetricOperand] = [
        RunEvent.metric(name),  # Single value
        RunEvent.metric(name).average(window),  # Aggregated
        RunEvent.metric(name).min(window),  # Aggregated
        RunEvent.metric(name).max(window),  # Aggregated
    ]

    for metric in metric_operands:
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
    name=printable_text,
    window=window_sizes,
    nonpositive_amount=nonpositive_amounts,
)
def test_declarative_metric_change_filter_requires_positive_delta(
    name: str, window: int, nonpositive_amount: int | float
):
    """Check that a `MetricChangeFilter` only accepts a positive quantity for `frac` or `diff`."""
    metric_operands = [
        RunEvent.metric(name),  # Single value
        RunEvent.metric(name).average(window),  # Aggregated
        RunEvent.metric(name).min(window),  # Aggregated
        RunEvent.metric(name).max(window),  # Aggregated
    ]

    for metric in metric_operands:
        with raises(ValueError):
            metric.changes_by(frac=nonpositive_amount)
        with raises(ValueError):
            metric.changes_by(diff=nonpositive_amount)
        with raises(ValueError):
            metric.increases_by(frac=nonpositive_amount)
        with raises(ValueError):
            metric.increases_by(diff=nonpositive_amount)
        with raises(ValueError):
            metric.decreases_by(frac=nonpositive_amount)
        with raises(ValueError):
            metric.decreases_by(diff=nonpositive_amount)


@given(
    metric_filter=metric_change_filters(
        name=printable_text,
        agg=none() | sample_with_randomcase(Agg),
        window=window_sizes,
        prior_window=window_sizes,
        threshold=positive_amounts,
        change_type=sample_with_randomcase(ChangeType),
        change_dir=sample_with_randomcase(ChangeDir),
    ),
)
def test_run_metric_change_events(project: Project, metric_filter: MetricChangeFilter):
    """Check that we can fully instantiate an `OnRunMetric` automation event, and that the event's filter is validated/serialized correctly."""
    run_filter = RunEvent.name.contains("my-run")
    event = OnRunMetric(scope=project, filter=run_filter & metric_filter)

    expected_metric_filter_dict = {
        "name": metric_filter.name,
        "agg_op": None if (metric_filter.agg is None) else metric_filter.agg.value,
        "current_window_size": metric_filter.window,
        "prior_window_size": metric_filter.prior_window,
        "change_dir": metric_filter.change_dir,
        "change_type": metric_filter.change_type,
        "change_amount": metric_filter.threshold,
    }
    expected_run_filter_dict = {
        "$and": [
            {"display_name": {"$contains": "my-run"}},
        ]
    }

    # Check that...
    # - the event has the expected event_type
    assert event.event_type is EventType.RUN_METRIC_CHANGE

    # - the metric filter has the expected JSON-serializable contents
    assert expected_metric_filter_dict == metric_filter.model_dump()

    # - the metric filter is parsed/validated correctly by pydantic
    inner_metric_filter = event.filter.metric.change_filter
    assert expected_metric_filter_dict == inner_metric_filter.model_dump()

    # - the accompanying run filter here is as expected
    assert expected_run_filter_dict == event.filter.run.model_dump()
