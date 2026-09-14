import json

from hypothesis import given
from hypothesis.strategies import dictionaries, sampled_from, text
from pydantic import ValidationError
from pytest import fixture, mark, raises
from wandb.automations import (
    ActionType,
    SendNotification,
    SendPromptToAria,
    SendWebhook,
)
from wandb.automations._generated import (
    AlertSeverity,
    TriggeredActionType,
    TriggerFields,
)
from wandb.automations.actions import SavedAriaAction
from wandb.automations.automations import Automation
from wandb.sdk.wandb_alerts import AlertLevel

from tests.unit_tests.test_filters._strategies import printable_text

from ._strategies import gql_ids, jsonables

VALID_ALERT_SEVERITY_ARG_VALUES = (
    # Where possible, accept both enum and (case-insensitive) string types for `severity`.
    *AlertSeverity,
    *AlertLevel,
    *(e.value.upper() for e in AlertSeverity),
    *(e.value.lower() for e in AlertSeverity),
)


def test_public_action_type_enum_is_subset_of_generated():
    """Check that the public `ActionType` enum is a subset of the schema-generated enum.

    This is a safeguard in case we've had to make any extra customizations
    (e.g. renaming members) to the public API definition.
    """
    public_enum_values = {e.value for e in ActionType}
    generated_enum_values = {e.value for e in TriggeredActionType}
    assert public_enum_values.issubset(generated_enum_values)


@given(
    integration_id=gql_ids(prefix="Integration"),
    title=printable_text(),
    message=printable_text(),
    severity=sampled_from(VALID_ALERT_SEVERITY_ARG_VALUES),
)
def test_notification_input_action_accepts_legacy_alert_args(
    integration_id, title, message, severity
):
    """Notification actions accept legacy `wandb.Alert` kwargs for continuity/convenience."""
    # Instantiate directly by the actual field names
    obj_from_normal_args = SendNotification(
        integration_id=integration_id,
        title=title,
        message=message,
        severity=severity,
    )

    # Instantiate by the legacy wandb.Alert arg names
    obj_from_legacy_args = SendNotification(
        integration_id=integration_id,
        title=title,
        text=message,
        level=severity,
    )

    assert obj_from_normal_args == obj_from_legacy_args

    dict_from_normal_args = obj_from_normal_args.model_dump()
    dict_from_legacy_args = obj_from_legacy_args.model_dump()
    assert dict_from_legacy_args == dict_from_normal_args

    # Check serialized JSON data directly, for good measure
    json_from_normal_args = obj_from_normal_args.model_dump_json()
    json_from_legacy_args = obj_from_legacy_args.model_dump_json()
    assert json.loads(json_from_legacy_args) == json.loads(json_from_normal_args)


@given(
    integration_id=gql_ids(prefix="Integration"),
    payload=dictionaries(keys=text(), values=jsonables()),
)
def test_webhook_input_action_accepts_deserialized_payload(integration_id, payload):
    """Webhook actions accept deserialized JSON dict payloads."""

    # Instantiate directly by the actual field names
    webhook_action = SendWebhook(
        integration_id=integration_id,
        request_payload=payload,
    )

    assert webhook_action.request_payload == payload

    serialized_payload = webhook_action.model_dump()["requestPayload"]

    assert isinstance(serialized_payload, str)
    assert json.loads(serialized_payload) == payload


@fixture
def trigger_node():
    def _trigger_node(action: dict) -> dict:
        return {
            "__typename": "Trigger",
            "id": "VHJpZ2dlcjoX",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": None,
            "name": "test-automation",
            "description": None,
            "enabled": True,
            "scope": {
                "__typename": "Project",
                "id": "UHJvamVjdDox",
                "name": "my-project",
            },
            "event": {
                "__typename": "FilterEventTriggeringCondition",
                "eventType": "CREATE_ARTIFACT",
                "filter": json.dumps({"filter": {"$or": [{"$and": []}]}}),
            },
            "action": action,
        }

    return _trigger_node


def test_aria_action_parses_when_listing(trigger_node):
    node = trigger_node({"__typename": "ARIATriggeredAction", "prompt": "Investigate"})
    trigger = TriggerFields.model_validate(node)
    automation = Automation.model_validate(trigger)
    assert isinstance(automation.action, SavedAriaAction)
    assert automation.action.prompt == "Investigate"
    assert automation.action.action_type is ActionType.ARIA


def test_send_prompt_to_aria_is_public():
    action = SendPromptToAria(prompt="  Summarize this run  ")
    assert action.action_type is ActionType.ARIA
    assert action.prompt == "Summarize this run"


@mark.parametrize(
    "prompt",
    ["", "   ", "x" * 4001, "é" * 2001],
    ids=["empty", "whitespace", "over-byte-limit", "multibyte-over-limit"],
)
def test_send_prompt_to_aria_rejects_invalid_prompts(prompt):
    with raises(ValidationError):
        SendPromptToAria(prompt=prompt)


def test_send_prompt_to_aria_accepts_max_prompt_size():
    action = SendPromptToAria(prompt="x" * 4000)
    assert action.prompt == "x" * 4000
