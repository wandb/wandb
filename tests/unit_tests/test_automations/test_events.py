from hypothesis import given
from hypothesis.strategies import integers
from pytest import mark, raises
from wandb.apis.public import Project
from wandb.sdk.automations.events import (
    ArtifactEvent,
    MetricFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
)

from ._strategies import ints_or_floats, printable_text


class TestDeclarativeEventSyntax:
    """Tests for self-consistency of the declarative event syntax."""

    @given(
        name=printable_text(),
        window=integers(1, 100),
        threshold=ints_or_floats(),
    )
    def test_run_metric_operator_vs_method_syntax_is_equivalent(
        self,
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

    def test_run_metric_threshold_cannot_be_aggregated_twice(self):
        """Check that run metric thresholds forbid multiple aggregations."""
        with raises(ValueError):
            RunEvent.metric("my-metric").average(5).average(10)
        with raises(ValueError):
            RunEvent.metric("my-metric").average(10).max(5)

    @mark.parametrize("window", argvalues=[5, 100])
    @mark.parametrize("agg", argvalues=["AVERAGE", "MIN", "MAX"])
    @mark.parametrize("threshold", argvalues=[123.45, 0, -10])
    def test_run_metric_events_without_run_filter(
        self, project: Project, window: int, agg: str, threshold: float
    ):
        name = "my-metric"
        cmp = "$gt"

        if agg == "AVERAGE":
            metric_filter = RunEvent.metric(name).average(window).gt(threshold)
        elif agg == "MIN":
            metric_filter = RunEvent.metric(name).min(window).gt(threshold)
        elif agg == "MAX":
            metric_filter = RunEvent.metric(name).max(window).gt(threshold)
        else:
            raise ValueError(f"Unhandled parameter: {agg=}")

        event = OnRunMetric(scope=project, filter=metric_filter)

        # Check that
        # - the metric filter has the expected contents
        # - the run+metric filter is parsed/validated correctly by pydantic
        expected_run_filter_dict = {"$and": []}
        expected_metric_filter = MetricFilter(
            name=name, window_size=window, agg_op=agg, cmp_op=cmp, threshold=threshold
        )

        assert expected_metric_filter == metric_filter

        assert expected_run_filter_dict == event.filter.run_filter.model_dump()
        assert expected_metric_filter == event.filter.metric_filter

    @mark.parametrize("window", argvalues=[5, 100])
    @mark.parametrize("agg", argvalues=["AVERAGE", "MIN", "MAX"])
    @mark.parametrize("threshold", argvalues=[123.45, 0, -10])
    def test_run_metric_events(
        self, project: Project, window: int, agg: str, threshold: float
    ):
        name = "my-metric"
        cmp = "$gt"

        if agg == "AVERAGE":
            metric_filter = RunEvent.metric(name).average(window).gt(threshold)
        elif agg == "MIN":
            metric_filter = RunEvent.metric(name).min(window).gt(threshold)
        elif agg == "MAX":
            metric_filter = RunEvent.metric(name).max(window).gt(threshold)
        else:
            raise ValueError(f"Unhandled parameter: {agg=}")

        run_filter = RunEvent.name.contains("my-run")

        event = OnRunMetric(scope=project, filter=run_filter & metric_filter)

        # Check that
        # - the metric filter has the expected contents
        # - the run+metric filter is parsed/validated correctly by pydantic
        expected_run_filter_dict = {"$and": [{"display_name": {"$contains": "my-run"}}]}
        expected_metric_filter = MetricFilter(
            name=name, window_size=window, agg_op=agg, cmp_op=cmp, threshold=threshold
        )

        assert expected_run_filter_dict == event.filter.run_filter.model_dump()
        assert expected_metric_filter == event.filter.metric_filter

    def test_link_artifact_events(self, project: Project):
        alias_regex = "prod-.*"

        event = OnLinkArtifact(
            scope=project,
            filter=ArtifactEvent.alias.matches_regex(alias_regex),
        )

        expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}
        assert expected_filter_dict == event.filter.model_dump()

    def test_create_artifact_events(self, project: Project):
        alias_regex = "prod-.*"

        event = OnCreateArtifact(
            scope=project,
            filter=ArtifactEvent.alias.matches_regex(alias_regex),
        )

        expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}
        assert expected_filter_dict == event.filter.model_dump()

    def test_add_artifact_alias_events(self, project: Project):
        alias_regex = "prod-.*"

        event = OnAddArtifactAlias(
            scope=project,
            filter=ArtifactEvent.alias.matches_regex(alias_regex),
        )

        expected_filter_dict = {"$or": [{"$and": [{"alias": {"$regex": alias_regex}}]}]}
        assert expected_filter_dict == event.filter.model_dump()
