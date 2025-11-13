from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from pytest import FixtureRequest, fixture, mark, raises
from wandb.automations import ActionType, EventType, NewAutomation
from wandb.automations._utils import (
    INVALID_INPUT_ACTIONS,
    INVALID_INPUT_EVENTS,
    prepare_to_create,
)
from wandb.automations.actions import InputAction
from wandb.automations.events import InputEvent


class TestPrepareToCreate:
    """Checks on the internal helper that prepares the GraphQL input for CreateFilterTrigger mutations."""

    def test_same_results_from_equivalent_args(self, input_event, input_action):
        """Check that preparing the CreateFilterTrigger input object by passing the same values in different ways produces identical results."""
        name = "test-name"
        description = "test-description"
        enabled = True

        attrs = dict(name=name, description=description, enabled=enabled)

        # REFERENCE: via NewAutomation instance as only positional arg
        expected_gql_input = prepare_to_create(
            NewAutomation(event=input_event, action=input_action, **attrs)
        )

        # ------------------------------------------------------------------------------
        # via only keyword args
        gql_input_via_kws = prepare_to_create(
            event=input_event, action=input_action, **attrs
        )

        assert expected_gql_input == gql_input_via_kws

        # ------------------------------------------------------------------------------
        # via `event >> action` and keyword args
        gql_input_via_event_action_and_kws = prepare_to_create(
            input_event >> input_action,
            **attrs,
        )

        assert expected_gql_input == gql_input_via_event_action_and_kws

        # ------------------------------------------------------------------------------
        # via NewAutomation instance and keyword args as overrides

        # Orig values deliberately different to check that they're overridden
        orig_obj = NewAutomation(
            event=input_event,
            action=input_action,
            name=f"REPLACED-{name}",
            description=f"REPLACED-{description}",
            enabled=not enabled,
        )
        gql_input_via_obj_and_kwargs = prepare_to_create(orig_obj, **attrs)

        assert expected_gql_input == gql_input_via_obj_and_kwargs

    @mark.parametrize("invalid_event_type", INVALID_INPUT_EVENTS)
    def test_prepare_to_create_rejects_excluded_event_types(
        self,
        input_event,
        input_action,
        invalid_event_type,
    ):
        """Check that prepare_to_create() fails if we try to assign a disallowed event type.

        Event types may be disallowed if e.g. the event type is deprecated or should otherwise
        be blocked on new/edited automations.
        """
        with raises(ValidationError):
            automation_to_create = NewAutomation(
                event=input_event,
                action=input_action,
                name="test-name",
            )
            automation_to_create.event.event_type = invalid_event_type
            prepare_to_create(automation_to_create)

    @mark.parametrize("invalid_action_type", INVALID_INPUT_ACTIONS)
    def test_prepare_to_create_rejects_excluded_action_types(
        self,
        input_event,
        input_action,
        invalid_action_type,
    ):
        """Check that prepare_to_create() fails if we try to assign a disallowed action type.

        Action types may be disallowed if e.g. the action type is deprecated or should otherwise
        be blocked on new/edited automations.
        """
        with raises(ValidationError):
            automation_to_create = NewAutomation(
                event=input_event,
                action=input_action,
                name="test-name",
            )
            automation_to_create.action.action_type = invalid_action_type
            prepare_to_create(automation_to_create)

    @fixture(
        params=[
            {"name": "test-name", "description": "test-description", "enabled": True},
            {"name": "test-name", "enabled": False},
            {"name": "test-name"},
        ]
    )
    def input_kwargs(self, request: FixtureRequest) -> dict[str, Any]:
        return request.param

    @fixture
    def prepared_vars(
        self,
        input_event: InputEvent,
        input_action: InputAction,
        input_kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        # If we were to actually send this new Automation to the server,
        # these the input variables for the GraphQL mutation.
        prepared = prepare_to_create(input_event >> input_action, **input_kwargs)
        return prepared.model_dump()

    def test_prepared_dict_values(
        self,
        scope,
        scope_type,
        event_type,
        action_type,
        input_kwargs,
        prepared_vars,
    ):
        """Check that preparing the GraphQL variables for creating a new Automation exports GraphQL variables with the expected keys and values."""
        # This only checks the simpler key-value pairs (without nested payloads).
        # We've omitted the more complicated event/action payloads, which will be checked separately.
        expected_subset = {
            "scopeType": scope_type,
            "scopeID": scope.id,
            "triggeringEventType": event_type,
            "triggeredActionType": action_type,
            **input_kwargs,
        }
        # Expected defaults, if they weren't provided
        if "enabled" not in input_kwargs:
            expected_subset["enabled"] = True

        assert expected_subset.keys() <= prepared_vars.keys()
        for k, expected_val in expected_subset.items():
            prepared_val = prepared_vars[k]
            assert prepared_val == expected_val

        # Check all expected keys are present
        other_expected_keys = {"eventFilter", "triggeredActionConfig"}
        assert {*expected_subset.keys(), *other_expected_keys} == prepared_vars.keys()

    # ----------------------------------------------------------------------------
    # Check prepared event payloads
    @fixture
    def event_filter_dict(self, prepared_vars) -> dict[str, Any]:
        """The prepared and DESERIALIZED `CreateFilterTriggerInput.eventFilter` payload."""
        return json.loads(prepared_vars["eventFilter"])

    @mark.parametrize("event_type", [EventType.RUN_METRIC_THRESHOLD], indirect=True)
    def test_event_payload_for_run_metric_threshold_events(
        self, input_event, event_filter_dict
    ):
        # Check the run filter
        orig_run_filter = input_event.filter.run
        run_filter_dict = json.loads(event_filter_dict["run_filter"])

        # Check that the filter is nested/wrapped as required by current backend/frontend logic
        assert run_filter_dict == orig_run_filter.model_dump()

        # Check the metric threshold condition
        orig_threshold_filter = input_event.filter.metric.threshold_filter
        threshold_dict = event_filter_dict["run_metric_filter"]["threshold_filter"]
        assert threshold_dict == {
            "agg_op": orig_threshold_filter.agg,
            "cmp_op": orig_threshold_filter.cmp,
            "threshold": orig_threshold_filter.threshold,
            "name": orig_threshold_filter.name,
            "window_size": orig_threshold_filter.window,
        }

    @mark.parametrize(
        "event_type",
        [
            EventType.CREATE_ARTIFACT,
            EventType.ADD_ARTIFACT_ALIAS,
            EventType.LINK_ARTIFACT,
        ],
        indirect=True,
    )
    def test_event_payload_for_artifact_mutation_events(
        self, input_event, event_filter_dict
    ):
        # Check that the filter is nested/wrapped as required by current backend/frontend logic
        #
        # Besides that, check the event payload: event filter should
        # otherwise match what was set on the event instance.
        assert event_filter_dict == input_event.filter.model_dump()

        # Current frontend logic needs these event filters to be wrapped like:
        #     {"$or": [{"$and": [...]}]}
        assert event_filter_dict.keys() == {"$or"}
        assert len(event_filter_dict["$or"]) == 1
        assert event_filter_dict["$or"][0].keys() == {"$and"}

    # ----------------------------------------------------------------------------
    # Check prepared action payloads
    @fixture
    def action_config_dict(self, prepared_vars) -> dict[str, Any]:
        """The prepared `CreateFilterTriggerInput.triggeredActionConfig` payload."""
        return prepared_vars["triggeredActionConfig"]

    @mark.parametrize("action_type", [ActionType.NO_OP], indirect=True)
    def test_action_payload_for_no_op_actions(self, action_config_dict):
        assert action_config_dict == {"noOpActionInput": {"noOp": True}}

    @mark.parametrize("action_type", [ActionType.NOTIFICATION], indirect=True)
    def test_action_payload_for_notification_actions(
        self, input_action, action_config_dict
    ):
        assert action_config_dict == {
            "notificationActionInput": {
                "integrationID": input_action.integration_id,
                "title": input_action.title,
                "message": input_action.message,
                "severity": input_action.severity,
            },
        }

    @mark.parametrize("action_type", [ActionType.GENERIC_WEBHOOK], indirect=True)
    def test_action_payload_for_webhook_actions(self, input_action, action_config_dict):
        assert action_config_dict == {
            "genericWebhookActionInput": {
                "integrationID": input_action.integration_id,
                "requestPayload": json.dumps(
                    input_action.request_payload, separators=(",", ":")
                ),
            },
        }
