from __future__ import annotations

import json

from pytest import mark
from wandb.automations import (
    ActionType,
    DoNothing,
    DoNotification,
    DoWebhook,
    EventType,
    OnRunMetric,
)
from wandb.automations._utils import prepare_create_input
from wandb.automations.events import RunMetricFilter

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
        scope,
        scope_type,
        event,
        event_type,
        action,
        action_type,
        name,
        description,
        enabled,
    ):
        """Check that we can instantiate a newly defined Automation (without actually sending it to the server)."""
        # If we were to actually send this new Automation to the server,
        # these would be passed as the GraphQL input variables
        prepared_input_vars = prepare_create_input(
            event >> action,
            name=name,
            description=description,
            enabled=enabled,
        ).model_dump(
            exclude_none=True,
        )

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

        assert expected.items() <= prepared_input_vars.items()

        # Check the event payload
        event_filter_json = prepared_input_vars["eventFilter"]
        if event_type is EventType.RUN_METRIC:
            assert isinstance(event, OnRunMetric)
            assert isinstance(event.filter, RunMetricFilter)

            event_filter_dict = json.loads(prepared_input_vars["eventFilter"])

            run_filter_dict = json.loads(event_filter_dict["run_filter"])
            threshold_filter_dict = event_filter_dict["run_metric_filter"][
                "threshold_filter"
            ]

            orig_run_filter = event.filter.run_filter
            orig_run_metric_filter = event.filter.run_metric_filter
            orig_threshold_filter = orig_run_metric_filter.threshold_filter

            assert isinstance(run_filter_dict, dict)
            assert isinstance(threshold_filter_dict, dict)

            assert run_filter_dict.keys() == {"$and"}
            assert run_filter_dict == orig_run_filter.model_dump()

            assert threshold_filter_dict == {
                "agg_op": orig_threshold_filter.agg,
                "cmp_op": orig_threshold_filter.cmp,
                "threshold": orig_threshold_filter.threshold,
                "name": orig_threshold_filter.name,
                "window_size": orig_threshold_filter.window,
            }

            assert threshold_filter_dict.keys() == {
                "agg_op",
                "cmp_op",
                "threshold",
                "name",
                "window_size",
            }

        else:
            # Event filter should be valid JSON and match what was passed the original event
            assert json.loads(event_filter_json) == event.filter.model_dump()

        # Check the action payload (triggeredActionConfig)
        action_config = prepared_input_vars["triggeredActionConfig"]
        if action_type is ActionType.NO_OP:
            assert isinstance(action, DoNothing)

            assert action_config == {
                "noOpActionInput": {"noOp": True},
            }

        elif action_type is ActionType.NOTIFICATION:
            assert isinstance(action, DoNotification)
            assert action_config == {
                "notificationActionInput": {
                    "integrationID": action.integration_id,
                    "title": action.title,
                    "message": action.message,
                    "severity": action.severity,
                },
            }

        elif action_type is ActionType.GENERIC_WEBHOOK:
            assert isinstance(action, DoWebhook)
            assert action_config == {
                "genericWebhookActionInput": {
                    "integrationID": action.integration_id,
                    "requestPayload": json.dumps(
                        action.request_payload, separators=(",", ":")
                    ),
                },
            }

        else:
            # This shouldn't happen unless we forget to test a new event or action
            raise ValueError(f"Unhandled action type: {action_type}")
