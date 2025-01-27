from __future__ import annotations

import json

from hypothesis import given
from hypothesis.strategies import integers
from pytest import mark
from wandb.apis.public import ArtifactCollection, Project
from wandb.sdk.automations import ActionType, DoNothing, DoNotification, DoWebhook
from wandb.sdk.automations._utils import prepare_create_input
from wandb.sdk.automations.events import (
    EventType,
    OnAddArtifactAlias,
    OnCreateArtifact,
    OnLinkArtifact,
    RunEvent,
)
from wandb.sdk.automations.scopes import ScopeType

from ._strategies import ints_or_floats, printable_text

pytestmark = [
    mark.wandb_core_only,
]


@mark.parametrize("description", argvalues=["test-automation-description", None])
@mark.parametrize("enabled", argvalues=[True, False], ids=["enabled", "disabled"])
def test_prepare_create_automation_input(
    scope: ArtifactCollection | Project,
    scope_type: ScopeType,
    event: OnCreateArtifact | OnLinkArtifact | OnAddArtifactAlias,
    event_type: EventType,
    action: DoNotification | DoWebhook | DoNothing,
    action_type: ActionType,
    description: str | None,
    enabled: bool,
):
    """Check that we can instantiate a newly defined Autoamtion (without actually sending it to the server)."""
    name: str = "test-automation-name"

    prepared_input = prepare_create_input(
        event >> action,
        name=name,
        description=description,
        enabled=enabled,
    )
    # If we were to actually send this new Automation to the server, these would be the GraphQL request parameters
    input_params = prepared_input.model_dump()

    assert input_params["name"] == name
    assert input_params["description"] == description
    assert input_params["enabled"] == enabled
    assert input_params["scopeType"] == scope_type.value
    assert input_params["scopeID"] == scope.id
    assert input_params["triggeringEventType"] == event_type.value
    assert input_params["triggeredActionType"] == action_type.value

    if event_filter_json := input_params["eventFilter"]:
        if event_type is EventType.RUN_METRIC:
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


@given(
    name=printable_text(),
    window=integers(1, 100),
    threshold=ints_or_floats(),
)
def test_metric_filter_repr_with_agg(name: str, window: int, threshold: float):
    """Check that the metric filter has the expected human-readable representation."""
    # These should be identical, but we test them separately to be sure
    avg_metric_filter = RunEvent.metric(name).average(window).gt(threshold)
    mean_metric_filter = RunEvent.metric(name).mean(window).gt(threshold)
    assert repr(f"AVERAGE(`{name}`) > {threshold}") in repr(avg_metric_filter)
    assert repr(f"AVERAGE(`{name}`) > {threshold}") in repr(mean_metric_filter)

    min_metric_filter = RunEvent.metric(name).min(window).gt(threshold)
    assert repr(f"MIN(`{name}`) > {threshold}") in repr(min_metric_filter)

    max_metric_filter = RunEvent.metric(name).max(window).gt(threshold)
    assert repr(f"MAX(`{name}`) > {threshold}") in repr(max_metric_filter)


@given(
    name=printable_text(),
    threshold=ints_or_floats(),
)
def test_metric_filter_repr_without_agg(name: str, threshold: float):
    """Check that the metric filter has the expected human-readable representation."""
    gt_metric_filter = RunEvent.metric(name).gt(threshold)
    assert repr(f"`{name}` > {threshold}") in repr(gt_metric_filter)

    gte_metric_filter = RunEvent.metric(name).gte(threshold)
    assert repr(f"`{name}` >= {threshold}") in repr(gte_metric_filter)

    lt_metric_filter = RunEvent.metric(name).lt(threshold)
    assert repr(f"`{name}` < {threshold}") in repr(lt_metric_filter)

    lte_metric_filter = RunEvent.metric(name).lte(threshold)
    assert repr(f"`{name}` <= {threshold}") in repr(lte_metric_filter)
