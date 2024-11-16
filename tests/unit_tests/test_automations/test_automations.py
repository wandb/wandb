from __future__ import annotations

import json
from typing import Any

from pytest import FixtureRequest, fixture, mark, param
from wandb.automations import (
    ActionType,
    DoNothing,
    DoNotification,
    DoWebhook,
    EventType,
    OnRunMetric,
)
from wandb.automations._utils import prepare_create_input
from wandb.automations.actions import InputAction
from wandb.automations.automations import NewAutomation
from wandb.automations.events import InputEvent, RunMetricFilter

pytestmark = [
    mark.wandb_core_only,
]


class TestPrepareGraphQLInput:
    """Checks for internal helpers that prepare input payloads for GraphQL requests."""

    def test_prepare_create_input_accepts_new_automation_without_syntactic_sugar(
        self, scope, input_event, input_action
    ):
        """Check that preparing the CreateFilterTrigger input object by passing the same values in different ways produces identical results."""
        prepared_from_object = prepare_create_input(
            NewAutomation(
                event=input_event,
                action=input_action,
                name="test-name",
                description="test-description",
                enabled=True,
            )
        )

        prepared_from_keyword_args = prepare_create_input(
            event=input_event,
            action=input_action,
            name="test-name",
            description="test-description",
            enabled=True,
        )

        prepared_from_event_to_action_syntax = prepare_create_input(
            input_event >> input_action,
            name="test-name",
            description="test-description",
            enabled=True,
        )

        prepared_object_and_override_kwargs = prepare_create_input(
            NewAutomation(
                event=input_event,
                action=input_action,
                name="old-name",
                description="old-description",
                enabled=False,
            ),
            name="test-name",
            description="test-description",
            enabled=True,
        )

        assert prepared_from_object == prepared_from_keyword_args
        assert prepared_from_object == prepared_from_event_to_action_syntax
        assert prepared_from_object == prepared_object_and_override_kwargs

    @fixture
    def name(self) -> str:
        return "test-name"

    @fixture(params=["test-description", None])
    def description(self, request: FixtureRequest) -> str | None:
        return request.param

    @fixture(params=[True, False], ids=["enabled", "disabled"])
    def enabled(self, request: FixtureRequest) -> bool:
        return request.param

    @fixture
    def prepared_vars(
        self,
        input_event: InputEvent,
        input_action: InputAction,
        name: str,
        description: str | None,
        enabled: bool,
    ) -> dict[str, Any]:
        # If we were to actually send this new Automation to the server,
        # these would be passed as the GraphQL input variables
        prepared = prepare_create_input(
            input_event >> input_action,
            name=name,
            description=description,
            enabled=enabled,
        )
        return prepared.model_dump(exclude_none=True)

    def test_prepare_create_input_dumps_expected_top_level_vars(
        self,
        scope,
        scope_type,
        event_type,
        action_type,
        name,
        description,
        enabled,
        prepared_vars,
    ):
        """Check that preparing the GraphQL variables for creating a new Automation exports GraphQL variables with the expected keys and values."""
        # This only checks the simpler key-value pairs (without nested payloads).
        # We've omitted the more complicated event/action payloads, which will be checked separately.
        expected = {
            "name": name,
            "enabled": enabled,
            "scopeType": scope_type,
            "scopeID": scope.id,
            "triggeringEventType": event_type,
            "triggeredActionType": action_type,
        }
        if description is not None:
            expected["description"] = description

        assert expected.items() <= prepared_vars.items()

    @mark.parametrize(
        "event_type",
        [
            EventType.RUN_METRIC,
            param(
                EventType.RUN_METRIC_CHANGE,
                marks=mark.skip(reason="Not implemented yet"),
            ),
        ],
        indirect=True,
    )
    def test_prepare_create_input_dumps_expected_run_event_payload(
        self, input_event, prepared_vars
    ):
        assert isinstance(input_event, OnRunMetric)
        assert isinstance(input_event.filter, RunMetricFilter)

        event_filter_dict = json.loads(prepared_vars["eventFilter"])

        run_filter_dict = json.loads(event_filter_dict["run_filter"])
        metric_filter_dict = event_filter_dict["run_metric_filter"]

        orig_run_filter = input_event.filter.run_filter
        orig_run_metric_filter = input_event.filter.run_metric_filter
        orig_threshold_filter = orig_run_metric_filter.threshold_filter

        assert isinstance(run_filter_dict, dict)
        assert isinstance(metric_filter_dict, dict)

        assert run_filter_dict.keys() == {"$and"}
        assert run_filter_dict == orig_run_filter.model_dump()

        assert metric_filter_dict == {
            "change_filter": None,
            "threshold_filter": {
                "agg_op": orig_threshold_filter.agg,
                "cmp_op": orig_threshold_filter.cmp,
                "threshold": orig_threshold_filter.threshold,
                "name": orig_threshold_filter.name,
                "window_size": orig_threshold_filter.window,
            },
        }

    @mark.parametrize(
        "event_type",
        [
            EventType.CREATE_ARTIFACT,
            EventType.ADD_ARTIFACT_ALIAS,
            EventType.LINK_MODEL,
        ],
        indirect=True,
    )
    def test_prepare_create_input_dumps_expected_event_payload_for_mutation_events(
        self, input_event, prepared_vars
    ):
        # Check the event payload: event filter should be valid JSON
        # and match what was passed the original event
        assert (
            json.loads(prepared_vars["eventFilter"]) == input_event.filter.model_dump()
        )

    @mark.parametrize("action_type", [ActionType.NO_OP], indirect=True)
    def test_prepare_create_input_dumps_expected_action_payload_for_no_op(
        self, input_action, prepared_vars
    ):
        assert isinstance(input_action, DoNothing)  # consistency check

        # Check the action payload (triggeredActionConfig)
        assert prepared_vars["triggeredActionConfig"] == {
            "noOpActionInput": {"noOp": True},
        }

    @mark.parametrize("action_type", [ActionType.NOTIFICATION], indirect=True)
    def test_prepare_create_input_dumps_expected_action_payload_for_notification(
        self, input_action, prepared_vars
    ):
        assert isinstance(input_action, DoNotification)  # consistency check

        # Check the action payload (triggeredActionConfig)
        assert prepared_vars["triggeredActionConfig"] == {
            "notificationActionInput": {
                "integrationID": input_action.integration_id,
                "title": input_action.title,
                "message": input_action.message,
                "severity": input_action.severity,
            },
        }

    @mark.parametrize("action_type", [ActionType.GENERIC_WEBHOOK], indirect=True)
    def test_prepare_create_input_dumps_expected_action_payload_for_webhook(
        self, input_action, prepared_vars
    ):
        assert isinstance(input_action, DoWebhook)  # consistency check

        # Check the action payload (triggeredActionConfig)
        assert prepared_vars["triggeredActionConfig"] == {
            "genericWebhookActionInput": {
                "integrationID": input_action.integration_id,
                "requestPayload": json.dumps(
                    input_action.request_payload, separators=(",", ":")
                ),
            },
        }
