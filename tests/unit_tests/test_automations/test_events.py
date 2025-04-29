"""Tests on behavior of Automation events."""

from __future__ import annotations

import json

from hypothesis import given
from hypothesis.strategies import SearchStrategy, integers, none, sampled_from
from pytest import mark, raises
from wandb.apis.public import Project
from wandb.automations import EventType, ScopeType
from wandb.automations._filters.run_metrics import Agg
from wandb.automations._generated import EventTriggeringConditionType
from wandb.automations.events import (
    ArtifactEvent,
    MetricThresholdFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    RunEvent,
)

from ._strategies import ints_or_floats, printable_text, sample_with_randomcase

cmp_vals: SearchStrategy[str] = sampled_from(["$gt", "$gte", "$lt", "$lte"])


def test_public_event_type_enum_matches_generated():
    """Check that the public `EventType` enum matches the schema-generated enum.

    This is a safeguard in case we've had to make any extra customizations
    (e.g. renaming members) to the public API definition.
    """
    public_enum_values = {e.value for e in EventType}
    generated_enum_values = {e.value for e in EventTriggeringConditionType}
    assert public_enum_values == generated_enum_values


@mark.parametrize(
    ("expr", "expected"),
    (
        (RunEvent.name.contains("my-run"), {"display_name": {"$contains": "my-run"}}),
        (RunEvent.name == "my-run", {"display_name": {"$eq": "my-run"}}),
        (RunEvent.name.eq("my-run"), {"display_name": {"$eq": "my-run"}}),
        (RunEvent.name != "my-run", {"display_name": {"$ne": "my-run"}}),
        (RunEvent.name.ne("my-run"), {"display_name": {"$ne": "my-run"}}),
        (RunEvent.name >= "my-run", {"display_name": {"$gte": "my-run"}}),
        (RunEvent.name.gte("my-run"), {"display_name": {"$gte": "my-run"}}),
        (RunEvent.name <= "my-run", {"display_name": {"$lte": "my-run"}}),
        (RunEvent.name.lte("my-run"), {"display_name": {"$lte": "my-run"}}),
        (RunEvent.name > "my-run", {"display_name": {"$gt": "my-run"}}),
        (RunEvent.name.gt("my-run"), {"display_name": {"$gt": "my-run"}}),
        (RunEvent.name < "my-run", {"display_name": {"$lt": "my-run"}}),
        (RunEvent.name.lt("my-run"), {"display_name": {"$lt": "my-run"}}),
    ),
)
def test_declarative_run_filter(expr, expected):
    assert expr.model_dump() == expected


@mark.parametrize(
    ("expr", "expected"),
    ((ArtifactEvent.alias.matches_regex("prod-.*"), {"alias": {"$regex": "prod-.*"}}),),
)
def test_declarative_artifact_filter(expr, expected):
    assert expr.model_dump() == expected


@given(
    name=printable_text,
    window=integers(1, 100),
    agg=none() | sampled_from([*Agg, *(e.value for e in Agg)]),
    cmp=cmp_vals,
    threshold=ints_or_floats,
)
def test_metric_threshold_filter_serialization(
    name: str, window: int, agg: str | None, cmp: str, threshold: float
):
    """Check that a normally-instantiated `MetricThresholdFilter` produces the expected JSON-serializable dict."""
    threshold_filter = MetricThresholdFilter(
        name=name,
        window=window,
        agg=agg,
        cmp=cmp,
        threshold=threshold,
    )
    expected_dict = {
        "name": name,
        "window_size": window,
        "agg_op": agg,
        "cmp_op": cmp,
        "threshold": threshold,
    }

    assert threshold_filter.model_dump() == expected_dict
    assert json.loads(threshold_filter.model_dump_json()) == expected_dict


@given(
    name=printable_text,
    window=integers(1, 100),
    agg=sample_with_randomcase(Agg),  # check case-insensitivity
    cmp=cmp_vals,
    threshold=ints_or_floats,
)
def test_run_metric_agg_threshold_filter_without_run_filter(
    project: Project, name: str, window: int, agg: str | Agg, cmp: str, threshold: float
):
    # Chain the method calls: the steps below parameterize over all possible combos of
    # chained method calls that would normally be written as, e.g.:
    #     RunEvent.metric(name).average(window).gt(threshold)
    #     RunEvent.metric(name).max(window).lte(threshold)
    run_metric = RunEvent.metric(name)

    # Chain the first method calls to declare the (maybe aggregated) metric expression
    agg_methodcallers = {
        Agg.AVERAGE: lambda: run_metric.average(window),
        Agg.MIN: lambda: run_metric.min(window),
        Agg.MAX: lambda: run_metric.max(window),
    }
    metric_expr = agg_methodcallers[Agg(agg)]()

    # Chain the next method call(s) to declare the evaluated threshold condition
    cmp_methodcallers = {
        "$gt": lambda: metric_expr.gt(threshold),
        "$gte": lambda: metric_expr.gte(threshold),
        "$lt": lambda: metric_expr.lt(threshold),
        "$lte": lambda: metric_expr.lte(threshold),
    }
    declared_metric_filter = cmp_methodcallers[cmp]()

    # ----------------------------------------------------------------------------
    event = OnRunMetric(scope=project, filter=declared_metric_filter)

    expected_metric_filter = MetricThresholdFilter(
        name=name, window=window, agg=agg, cmp=cmp, threshold=threshold
    )
    expected_metric_filter_dict = {
        "name": name,
        "window_size": window,
        "agg_op": Agg(agg).value,  # Expect the string value
        "cmp_op": cmp,
        "threshold": threshold,
    }

    # Check that...
    # - the metric filter has the expected contents
    assert expected_metric_filter == declared_metric_filter
    assert expected_metric_filter_dict == declared_metric_filter.model_dump()

    # - the metric filter is parsed/validated correctly by pydantic
    actual_metric_filter = event.filter.metric.threshold_filter
    assert expected_metric_filter == actual_metric_filter
    assert expected_metric_filter_dict == actual_metric_filter.model_dump()

    # - the accompanying run filter here is as expected
    expected_run_filter_dict = {"$and": []}
    assert expected_run_filter_dict == event.filter.run.model_dump()


@given(
    name=printable_text,
    window=integers(1, 100),
    agg=sampled_from([*Agg, *(e.value for e in Agg)]),
    cmp=cmp_vals,
    threshold=ints_or_floats,
)
def test_run_metric_threshold_events(
    project: Project, name: str, window: int, agg: Agg | str, cmp: str, threshold: float
):
    # Chain the method calls: the steps below parameterize over all possible combos of
    # chained method calls that would normally be written as, e.g.:
    #     RunEvent.metric(name).average(window).gt(threshold)
    #     RunEvent.metric(name).max(window).lte(threshold)
    run_metric = RunEvent.metric(name)

    # Chain the first method calls to declare the (maybe aggregated) metric expression
    agg_methodcallers = {
        Agg.AVERAGE: lambda: run_metric.average(window),
        Agg.MIN: lambda: run_metric.min(window),
        Agg.MAX: lambda: run_metric.max(window),
    }
    metric_expr = agg_methodcallers[Agg(agg)]()

    # Chain the next method call(s) to declare the evaluated threshold condition
    cmp_methodcallers = {
        "$gt": lambda: metric_expr.gt(threshold),
        "$gte": lambda: metric_expr.gte(threshold),
        "$lt": lambda: metric_expr.lt(threshold),
        "$lte": lambda: metric_expr.lte(threshold),
    }
    declared_metric_filter = cmp_methodcallers[cmp]()

    # ----------------------------------------------------------------------------
    declared_run_filter = RunEvent.name.contains("my-run")

    # ----------------------------------------------------------------------------
    event = OnRunMetric(
        scope=project, filter=declared_run_filter & declared_metric_filter
    )

    expected_metric_filter = MetricThresholdFilter(
        name=name, window=window, agg=agg, cmp=cmp, threshold=threshold
    )
    expected_metric_filter_dict = {
        "name": name,
        "window_size": window,
        "agg_op": Agg(agg).value,  # Expect the string value
        "cmp_op": cmp,
        "threshold": threshold,
    }

    # Check that...
    # - the metric filter has the expected contents
    assert expected_metric_filter == declared_metric_filter
    assert expected_metric_filter_dict == declared_metric_filter.model_dump()

    # - the metric filter is parsed/validated correctly by pydantic
    actual_metric_filter = event.filter.metric.threshold_filter
    assert expected_metric_filter == actual_metric_filter
    assert expected_metric_filter_dict == actual_metric_filter.model_dump()

    # - the accompanying run filter here is as expected
    expected_run_filter_dict = {"$and": [{"display_name": {"$contains": "my-run"}}]}
    assert expected_run_filter_dict == event.filter.run.model_dump()


def test_link_artifact_events(scope):
    alias_regex = "prod-.*"
    declared_filter = ArtifactEvent.alias.matches_regex(alias_regex)

    event = OnLinkArtifact(scope=scope, filter=declared_filter)

    expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}
    assert expected_filter_dict == event.filter.model_dump()


# Only ArtifactCollection scopes are supported for CREATE_ARTIFACT events
@mark.parametrize("scope_type", [ScopeType.ARTIFACT_COLLECTION], indirect=True)
def test_create_artifact_events(scope):
    alias_regex = "prod-.*"
    declared_filter = ArtifactEvent.alias.matches_regex(alias_regex)

    event = OnCreateArtifact(scope=scope, filter=declared_filter)

    expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}
    assert expected_filter_dict == event.filter.model_dump()


def test_add_artifact_alias_events(scope):
    alias_regex = "prod-.*"
    declared_filter = ArtifactEvent.alias.matches_regex(alias_regex)

    event = OnAddArtifactAlias(scope=scope, filter=declared_filter)

    expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}
    assert expected_filter_dict == event.filter.model_dump()


# Checks on self-consistency of syntactic sugar and other quality-of-life features
@given(
    name=printable_text,
    window=integers(1, 100),
    threshold=ints_or_floats,
)
def test_run_metric_operator_vs_method_syntax_is_equivalent(
    name: str,
    window: int,
    threshold: float,
):
    """Check that metric thresholds defined via comparison operators vs method-call syntax are equivalent."""
    metric_expressions = [
        RunEvent.metric(name).average(window),  # Aggregate
        RunEvent.metric(name).mean(window),  # Aggregate
        RunEvent.metric(name).min(window),  # Aggregate
        RunEvent.metric(name).max(window),  # Aggregate
        RunEvent.metric(name),  # Single value
    ]

    for metric_expr in metric_expressions:
        assert (metric_expr > threshold) == metric_expr.gt(threshold)
        assert (metric_expr >= threshold) == metric_expr.gte(threshold)
        assert (metric_expr < threshold) == metric_expr.lt(threshold)
        assert (metric_expr <= threshold) == metric_expr.lte(threshold)


def test_run_metric_threshold_cannot_be_aggregated_twice():
    """Check that run metric thresholds forbid multiple aggregations."""
    with raises(AttributeError):
        RunEvent.metric("my-metric").average(5).average(10)
    with raises(AttributeError):
        RunEvent.metric("my-metric").average(10).max(5)


@given(
    name=printable_text,
    window=integers(1, 100),
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
    metric_agg_expressions = {
        Agg.AVERAGE: RunEvent.metric(name).average(window),
        Agg.AVERAGE: RunEvent.metric(name).mean(window),
        Agg.MIN: RunEvent.metric(name).min(window),
        Agg.MAX: RunEvent.metric(name).max(window),
    }

    for agg, metric_agg_expr in metric_agg_expressions.items():
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
