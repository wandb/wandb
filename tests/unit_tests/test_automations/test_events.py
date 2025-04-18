"""Tests on behavior of Automation events."""

from __future__ import annotations

from hypothesis import given
from hypothesis.strategies import integers, sampled_from
from pytest import raises
from wandb.apis.public import ArtifactCollection, Project
from wandb.automations.events import (
    Agg,
    ArtifactEvent,
    MetricThresholdFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
)

from ._strategies import ints_or_floats, printable_text


def test_declarative_run_filter():
    run_filter = RunEvent.name.contains("my-run")
    assert run_filter.model_dump() == {"display_name": {"$contains": "my-run"}}


def test_declarative_artifact_filter():
    artifact_filter = ArtifactEvent.alias.matches_regex("prod-.*")
    assert artifact_filter.model_dump() == {"alias": {"$regex": "prod-.*"}}


@given(
    window=integers(1, 100),
    agg=sampled_from([*Agg, *(e.value for e in Agg)]),
    threshold=ints_or_floats(),
)
def test_run_metric_events_without_run_filter(
    project: Project, window: int, agg: str, threshold: float
):
    name = "my-metric"
    cmp = "$gt"

    agg_enum = Agg(agg)
    if agg_enum is Agg.AVERAGE:
        threshold_filter = RunEvent.metric(name).average(window).gt(threshold)
    elif agg_enum is Agg.MIN:
        threshold_filter = RunEvent.metric(name).min(window).gt(threshold)
    elif agg_enum is Agg.MAX:
        threshold_filter = RunEvent.metric(name).max(window).gt(threshold)
    else:
        raise ValueError(f"Unhandled parameter: {agg=}")

    event = OnRunMetric(scope=project, filter=threshold_filter)

    # Check that
    # - the metric filter has the expected contents
    # - the run+metric filter is parsed/validated correctly by pydantic
    expected_run_filter_dict = {"$and": []}
    expected_threshold_filter = MetricThresholdFilter(
        name=name, window_size=window, agg_op=agg, cmp_op=cmp, threshold=threshold
    )

    assert expected_threshold_filter == threshold_filter

    assert expected_run_filter_dict == event.filter.run_filter.model_dump()
    assert expected_threshold_filter == event.filter.run_metric_filter.threshold_filter


@given(
    window=integers(1, 100),
    agg=sampled_from([*Agg, *(e.value for e in Agg)]),
    threshold=ints_or_floats(),
)
def test_run_metric_events(
    project: Project, window: int, agg: Agg | str, threshold: float
):
    name = "my-metric"
    cmp = "$gt"

    agg_enum = Agg(agg)
    if agg_enum is Agg.AVERAGE:
        threshold_filter = RunEvent.metric(name).average(window).gt(threshold)
    elif agg_enum is Agg.MIN:
        threshold_filter = RunEvent.metric(name).min(window).gt(threshold)
    elif agg_enum is Agg.MAX:
        threshold_filter = RunEvent.metric(name).max(window).gt(threshold)
    else:
        raise ValueError(f"Unhandled parameter: {agg=}")

    run_filter = RunEvent.name.contains("my-run")

    event = OnRunMetric(scope=project, filter=run_filter & threshold_filter)

    # Check that
    # - the metric filter has the expected contents
    # - the run+metric filter is parsed/validated correctly by pydantic
    expected_run_filter_dict = {"$and": [{"display_name": {"$contains": "my-run"}}]}
    expected_threshold_filter = MetricThresholdFilter(
        name=name, window_size=window, agg_op=agg, cmp_op=cmp, threshold=threshold
    )

    assert expected_run_filter_dict == event.filter.run_filter.model_dump()
    assert expected_threshold_filter == event.filter.run_metric_filter.threshold_filter


def test_link_artifact_events(project: Project):
    alias_regex = "prod-.*"

    event = OnLinkArtifact(
        scope=project,
        filter=ArtifactEvent.alias.matches_regex(alias_regex),
    )

    expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}
    assert expected_filter_dict == event.filter.model_dump()


def test_create_artifact_events(artifact_collection: ArtifactCollection):
    alias_regex = "prod-.*"

    event = OnCreateArtifact(
        scope=artifact_collection,
        filter=ArtifactEvent.alias.matches_regex(alias_regex),
    )

    expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}
    assert expected_filter_dict == event.filter.model_dump()


def test_add_artifact_alias_events(project: Project):
    alias_regex = "prod-.*"

    event = OnAddArtifactAlias(
        scope=project,
        filter=ArtifactEvent.alias.matches_regex(alias_regex),
    )

    expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}
    assert expected_filter_dict == event.filter.model_dump()


# Checks on self-consistency of syntactic sugar and other quality-of-life features
@given(
    name=printable_text(),
    window=integers(1, 100),
    threshold=ints_or_floats(),
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
    with raises(ValueError):
        RunEvent.metric("my-metric").average(5).average(10)
    with raises(ValueError):
        RunEvent.metric("my-metric").average(10).max(5)


@given(
    name=printable_text(),
    threshold=ints_or_floats(),
    op=sampled_from([">", ">=", "<", "<="]),
)
def test_metric_filter_repr_without_agg(name: str, threshold: float, op: str):
    """Check that the filter on a single-value metric has the expected human-readable representation."""
    metric_expr = RunEvent.metric(name)

    if op == ">":
        threshold_filter = metric_expr.gt(threshold)
    elif op == ">=":
        threshold_filter = metric_expr.gte(threshold)
    elif op == "<":
        threshold_filter = metric_expr.lt(threshold)
    elif op == "<=":
        threshold_filter = metric_expr.lte(threshold)

    assert repr(f"{name} {op} {threshold}") in repr(threshold_filter)


@given(
    name=printable_text(),
    window=integers(1, 100),
    threshold=ints_or_floats(),
    op=sampled_from([">", ">=", "<", "<="]),
    agg=sampled_from(list(Agg)),
)
def test_metric_filter_repr_with_agg(
    name: str, window: int, threshold: float, op: str, agg: Agg
):
    """Check that the filter on an aggregated metric has the expected human-readable representation."""

    if agg is Agg.AVERAGE:
        metric_expr = RunEvent.metric(name).average(window)
    elif agg is Agg.MIN:
        metric_expr = RunEvent.metric(name).min(window)
    elif agg is Agg.MAX:
        metric_expr = RunEvent.metric(name).max(window)
    else:
        raise ValueError(f"Unhandled aggregation: {agg!r}")

    if op == ">":
        threshold_filter = metric_expr.gt(threshold)
    elif op == ">=":
        threshold_filter = metric_expr.gte(threshold)
    elif op == "<":
        threshold_filter = metric_expr.lt(threshold)
    elif op == "<=":
        threshold_filter = metric_expr.lte(threshold)
    else:
        raise ValueError(f"Unhandled comparison operator: {op!r}")

    assert repr(f"{agg.value}({name}) {op} {threshold}") in repr(threshold_filter)
