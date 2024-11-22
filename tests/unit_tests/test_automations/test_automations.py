from __future__ import annotations

import json

from pytest import mark
from wandb.apis.public import ArtifactCollection, Project
from wandb.sdk.automations import ActionType, DoNotification, DoWebhook
from wandb.sdk.automations._utils import prepare_create_input
from wandb.sdk.automations.events import EventType

pytestmark = [
    mark.wandb_core_only,
]


class TestPrepareGraphQLInput:
    """Checks for internal helpers that prepare input payloads for GraphQL requests."""

    @mark.parametrize(
        "name",
        ["test-name"],
    )
    @mark.parametrize(
        "description",
        ["test-description", None],
    )
    @mark.parametrize(
        "enabled",
        [True, False],
        ids=["enabled", "disabled"],
    )
    def test_prepare_create_input(
        self,
        scope: ArtifactCollection | Project,
        scope_type,
        event,
        event_type,
        action,
        action_type,
        name,
        description,
        enabled,
    ):
        """Check that we can instantiate a newly defined Autoamtion (without actually sending it to the server)."""
        prepared = prepare_create_input(
            event >> action,
            name=name,
            description=description,
            enabled=enabled,
        )

        # If we were to actually send this new Automation to the server,
        # these would be passed as the GraphQL input variables
        payload = prepared.model_dump(exclude_none=True)

        # This only checks a subset of the expected key-value pairs.
        # We've omitted the more complicated event/action payloads, which will be checked separately
        expected = {
            "name": name,
            "description": description,
            "enabled": enabled,
            "scopeType": scope_type.value,
            "scopeID": scope.id,
            "triggeringEventType": event_type.value,
            "triggeredActionType": action_type.value,
        }
        expected = {k: v for k, v in expected.items() if v is not None}

        assert expected.items() <= payload.items()

        # Check the event payload
        if event_filter_json := payload["eventFilter"]:
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

        # Check the action payload
        if action_type is ActionType.NO_OP:
            expected_key = "noOpActionInput"
            expected_action_payload = {"noOp": True}

        elif action_type is ActionType.NOTIFICATION:
            expected_key = "notificationActionInput"
            assert isinstance(action, DoNotification)
            expected_action_payload = {
                "integrationID": action.integration_id,
                "title": action.title,
                "message": action.message,
                "severity": action.severity,
            }

        elif action_type is ActionType.GENERIC_WEBHOOK:
            expected_key = "genericWebhookActionInput"
            assert isinstance(action, DoWebhook)
            expected_action_payload = {
                "integrationID": action.integration_id,
                "requestPayload": json.dumps(
                    action.request_payload, separators=(",", ":")
                ),
            }

        else:
            raise ValueError(f"Unhandled action type: {action_type}")

        action_config = payload["triggeredActionConfig"]

        assert action_config.keys() == {expected_key}
        assert action_config[expected_key] == expected_action_payload
