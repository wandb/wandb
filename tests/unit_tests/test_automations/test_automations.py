from __future__ import annotations

import json
from operator import itemgetter
from typing import Literal

from hypothesis import HealthCheck, given, settings
from hypothesis.strategies import integers
from pytest import mark, raises
from wandb.apis import public
from wandb.sdk.automations._utils import prepare_create_trigger_input
from wandb.sdk.automations.actions import ActionType, DoNotification, DoWebhook
from wandb.sdk.automations.events import (
    ArtifactEvent,
    EventType,
    MetricFilter,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    OnRunMetric,
    RunEvent,
    RunFilter,
)
from wandb.sdk.automations.filters import And
from wandb.sdk.automations.scopes import ScopeType

from ._strategies import finite_floats, printable_text


@mark.parametrize("name", argvalues=["test-automation-name"])
@mark.parametrize("description", argvalues=["test-automation-description", None])
@mark.parametrize("enabled", argvalues=[True, False], ids=["enabled", "disabled"])
def test_define_new_automation(
    scope: public.ArtifactCollection | public.Project,
    scope_type: ScopeType,
    event: OnCreateArtifact | OnLinkArtifact | OnAddArtifactAlias,
    event_type: EventType,
    action: DoNotification | DoWebhook,
    action_type: ActionType,
    name: Literal["test automation name"],
    description: None | Literal["This is a description"],
    enabled: bool,
):
    """Check that we can instantiate a newly defined Autoamtion (without actually sending it to the server)."""
    prepared_input = prepare_create_trigger_input(
        event >> action,
        name=name,
        description=description,
        enabled=enabled,
    )
    # If we were to actually send this new Automation to the server, these would be the GraphQL request parameters
    input_params = prepared_input.model_dump()

    expected_params = {
        "name": name,
        "description": description,
        "enabled": enabled,
        "scopeType": scope_type.value,
        "scopeID": scope.id,
        "triggeringEventType": event_type.value,
        "triggeredActionType": action_type.value,
    }

    get_values = itemgetter(*expected_params)
    assert get_values(expected_params) == get_values(input_params)

    if (event_filter_json := input_params["eventFilter"]) is not None:
        pass
    elif event_type is EventType.RUN_METRIC:
        event_filter = json.loads(event_filter_json)

        run_filter = json.loads(event_filter["run_filter"])
        metric_filter = json.loads(event_filter["metric_filter"])

        assert isinstance(run_filter, dict)
        assert isinstance(metric_filter, dict)

        assert run_filter.keys() == {"$and"}
        assert metric_filter.keys() == {
            "agg_op",
            "cmp_op",
            "threshold",
            "name",
            "window_size",
        }

    else:
        # Event filter should be valid JSON and match what was passed the original event
        assert json.loads(event_filter_json) == event.filter.model_dump()


class TestDeclarativeEventSyntax:
    """Tests for self-consistency of the declarative event syntax."""

    @settings(suppress_health_check=[HealthCheck.differing_executors])
    @given(
        name=printable_text(),
        window=integers(min_value=1, max_value=100),
        threshold=integers() | finite_floats(),
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

    def test_declarative_run_metric_events(self, project: public.Project):
        name = "my-metric"
        window = 5
        agg = "AVERAGE"
        cmp = "$gt"
        threshold = 123.45

        expected_metric_filter = MetricFilter(
            name=name,
            window_size=window,
            agg_op=agg,
            cmp_op=cmp,
            threshold=threshold,
        )

        metric_filter = RunEvent.metric(name).average(window).gt(threshold)

        # Check that the metric filter has both the expected contents and human-readable representation
        assert f"{agg}(`{name}`) > {threshold}" in repr(metric_filter)
        assert expected_metric_filter == metric_filter

        # Check that the metric filter is parsed/validated correctly by pydantic
        event = OnRunMetric(
            scope=project,
            filter=metric_filter,
        )
        assert RunFilter() == event.filter.run_filter
        assert expected_metric_filter == event.filter.metric_filter

        # Check that the run+metric filter is parsed/validated correctly by pydantic
        run_filter = RunEvent.name.contains("my-run")
        metric_filter = RunEvent.metric(name).average(window).gt(threshold)
        event = OnRunMetric(
            scope=project,
            filter=run_filter & metric_filter,
        )

        expected_run_filter_dict = {"$and": [{"display_name": {"$contains": "my-run"}}]}
        expected_run_filter = RunFilter.model_validate(expected_run_filter_dict)

        assert expected_run_filter_dict == event.filter.run_filter.model_dump()
        assert expected_run_filter == event.filter.run_filter
        assert expected_metric_filter == event.filter.metric_filter

    def test_declarative_link_artifact_events(self, project: public.Project):
        expected_filter = And(
            other=[
                {
                    "alias": {
                        "$regex": "prod-.*",
                    }
                }
            ]
        )

        event = OnLinkArtifact(
            scope=project,
            filter=ArtifactEvent.alias.matches_regex("prod-.*"),
        )

        assert expected_filter == event.filter
