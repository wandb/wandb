"""Tests on behavior of Automation events."""

from __future__ import annotations

from operator import methodcaller

from hypothesis import given
from hypothesis.strategies import integers, none
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
    OnRunMetric,
    RunEvent,
)

from ._strategies import (
    cmp_op_keys,
    ints_or_floats,
    metric_threshold_filters,
    printable_text,
    sample_with_randomcase,
)


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
    agg=none() | sample_with_randomcase(Agg),  # check case-insensitivity
    cmp=cmp_op_keys,
    threshold=ints_or_floats,
)
def test_run_metric_agg_threshold_filter_without_run_filter(
    project: Project,
    name: str,
    window: int,
    agg: str | Agg | None,
    cmp: str,
    threshold: float,
):
    # Chain the method calls: the steps below parameterize over all possible combos of
    # chained method calls that would normally be written as, e.g.:
    #     RunEvent.metric(name).average(window).gt(threshold)
    #     RunEvent.metric(name).max(window).lte(threshold)
    agg_enum = None if (agg is None) else Agg(agg)

    # Chain the first method calls to declare the (maybe aggregated) metric expression
    agg_methodcallers = {
        Agg.AVG: methodcaller("average", window),
        Agg.MIN: methodcaller("min", window),
        Agg.MAX: methodcaller("max", window),
        None: lambda x: x,  # Pass through, no aggregation
    }

    # Chain the next method call(s) to declare the evaluated threshold condition
    cmp_methodcallers = {
        "$gt": methodcaller("gt", threshold),
        "$gte": methodcaller("gte", threshold),
        "$lt": methodcaller("lt", threshold),
        "$lte": methodcaller("lte", threshold),
    }

    # Self-explanatory
    run_metric = RunEvent.metric(name)

    # Equivalent to e.g.: `run_metric -> run_metric.average(window)`
    metric_expr = agg_methodcallers[agg_enum](run_metric)

    # Equivalent to e.g.: `metric_expr -> metric_expr.gt(threshold)`
    declared_metric_filter = cmp_methodcallers[cmp](metric_expr)

    # ----------------------------------------------------------------------------
    event = OnRunMetric(scope=project, filter=declared_metric_filter)

    expected_window = 1 if (agg_enum is None) else window
    expected_agg_op = None if (agg_enum is None) else agg_enum.value
    expected_metric_filter = MetricThresholdFilter(
        name=name,
        window=expected_window,
        agg=expected_agg_op,
        cmp=cmp,
        threshold=threshold,
    )
    expected_metric_filter_dict = {
        "name": name,
        "window_size": expected_window,
        "agg_op": expected_agg_op,
        "cmp_op": cmp,
        "threshold": threshold,
    }

    expected_run_filter_dict = {"$and": []}

    # Check that...
    # - the metric filter has the expected contents
    assert isinstance(declared_metric_filter, MetricThresholdFilter)
    assert dict(expected_metric_filter) == dict(declared_metric_filter)
    assert expected_metric_filter_dict == declared_metric_filter.model_dump()

    # - the metric filter is parsed/validated correctly by pydantic
    inner_metric_filter = event.filter.metric.threshold_filter
    assert dict(expected_metric_filter) == dict(inner_metric_filter)
    assert expected_metric_filter_dict == inner_metric_filter.model_dump()

    # - the accompanying run filter here is as expected
    assert expected_run_filter_dict == event.filter.run.model_dump()


@given(
    metric_filter=metric_threshold_filters(),
)
def test_run_metric_threshold_events(
    project: Project, metric_filter: MetricThresholdFilter
):
    run_filter = RunEvent.name.contains("my-run")

    # ----------------------------------------------------------------------------
    event = OnRunMetric(scope=project, filter=run_filter & metric_filter)

    expected_metric_filter_dict = {
        "name": metric_filter.name,
        "window_size": metric_filter.window,
        "agg_op": None if (metric_filter.agg is None) else metric_filter.agg.value,
        "cmp_op": metric_filter.cmp,
        "threshold": metric_filter.threshold,
    }
    expected_run_filter_dict = {
        "$and": [
            {"display_name": {"$contains": "my-run"}},
        ]
    }

    # Check that...
    # - the event has the expected event_type
    assert event.event_type is EventType.RUN_METRIC_THRESHOLD

    # - the metric filter has the expected JSON-serializable contents
    assert expected_metric_filter_dict == metric_filter.model_dump()

    # - the metric filter is parsed/validated correctly by pydantic
    inner_metric_filter = event.filter.metric.threshold_filter
    assert expected_metric_filter_dict == inner_metric_filter.model_dump()

    # - the accompanying run filter here is as expected
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
