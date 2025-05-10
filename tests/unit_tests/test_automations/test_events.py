"""Tests on behavior of Automation events."""

from __future__ import annotations

from hypothesis import given
from pytest import mark
from wandb.apis.public import Project
from wandb.automations import (
    ArtifactEvent,
    EventType,
    MetricChangeFilter,
    MetricThresholdFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
    ScopeType,
)
from wandb.automations._generated import EventTriggeringConditionType

from ._strategies import metric_change_filters, metric_threshold_filters


def test_public_event_type_enum_matches_generated():
    """Check that the public `EventType` enum is a subset of the schema-generated enum.

    This is a safeguard in case we've had to make any extra customizations
    (e.g. renaming members) to the public API definition.
    """
    public_enum_values = {e.value for e in EventType}
    generated_enum_values = {e.value for e in EventTriggeringConditionType}
    assert public_enum_values <= generated_enum_values


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


@given(metric_filter=metric_threshold_filters())
def test_run_metric_threshold_events(
    project: Project, metric_filter: MetricThresholdFilter
):
    """Check that we can fully instantiate an `OnRunMetric` event with a metric THRESHOLD filter, and that the event's filter is validated/serialized correctly."""
    run_filter = RunEvent.name.contains("my-run")

    event = OnRunMetric(scope=project, filter=run_filter & metric_filter)

    # ----------------------------------------------------------------------------
    expected_metric_filter_dict = {
        "name": metric_filter.name,
        "window_size": metric_filter.window,
        "agg_op": None if (metric_filter.agg is None) else metric_filter.agg.value,
        "cmp_op": metric_filter.cmp,
        "threshold": metric_filter.threshold,
    }
    expected_run_filter_dict = {"$and": [{"display_name": {"$contains": "my-run"}}]}

    # ----------------------------------------------------------------------------
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


@given(metric_filter=metric_threshold_filters())
def test_run_metric_threshold_events_without_run_filter(
    project: Project, metric_filter: MetricThresholdFilter
):
    """Check that we can fully instantiate an `OnRunMetric` event with a metric THRESHOLD filter, even if we don't provide an explicit run filter."""
    event = OnRunMetric(scope=project, filter=metric_filter)

    expected_metric_filter_dict = {
        "name": metric_filter.name,
        "window_size": metric_filter.window,
        "agg_op": None if (metric_filter.agg is None) else metric_filter.agg.value,
        "cmp_op": metric_filter.cmp,
        "threshold": metric_filter.threshold,
    }
    expected_run_filter_dict = {"$and": []}

    # ----------------------------------------------------------------------------
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


@given(metric_filter=metric_change_filters())
def test_run_metric_change_events(project: Project, metric_filter: MetricChangeFilter):
    """Check that we can fully instantiate an `OnRunMetric` event with a metric CHANGE filter, and that the event's filter is validated/serialized correctly."""
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
    expected_run_filter_dict = {"$and": [{"display_name": {"$contains": "my-run"}}]}

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


@given(metric_filter=metric_change_filters())
def test_run_metric_change_events_without_run_filter(
    project: Project, metric_filter: MetricChangeFilter
):
    """Check that we can fully instantiate an `OnRunMetric` event with a metric CHANGE filter, even if we don't provide an explicit run filter."""
    event = OnRunMetric(scope=project, filter=metric_filter)

    expected_metric_filter_dict = {
        "name": metric_filter.name,
        "agg_op": None if (metric_filter.agg is None) else metric_filter.agg.value,
        "current_window_size": metric_filter.window,
        "prior_window_size": metric_filter.prior_window,
        "change_dir": metric_filter.change_dir,
        "change_type": metric_filter.change_type,
        "change_amount": metric_filter.threshold,
    }
    expected_run_filter_dict = {"$and": []}

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


def test_link_artifact_events(scope):
    alias_regex = "prod-.*"
    declared_filter = ArtifactEvent.alias.matches_regex(alias_regex)
    expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}

    event = OnLinkArtifact(scope=scope, filter=declared_filter)

    assert expected_filter_dict == event.filter.model_dump()


# Only ArtifactCollection scopes are supported for CREATE_ARTIFACT events
@mark.parametrize("scope_type", [ScopeType.ARTIFACT_COLLECTION], indirect=True)
def test_create_artifact_events(scope):
    alias_regex = "prod-.*"
    declared_filter = ArtifactEvent.alias.matches_regex(alias_regex)
    expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}

    event = OnCreateArtifact(scope=scope, filter=declared_filter)

    assert expected_filter_dict == event.filter.model_dump()


def test_add_artifact_alias_events(scope):
    alias_regex = "prod-.*"
    declared_filter = ArtifactEvent.alias.matches_regex(alias_regex)
    expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}

    event = OnAddArtifactAlias(scope=scope, filter=declared_filter)

    assert expected_filter_dict == event.filter.model_dump()
