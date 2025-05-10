import json

from hypothesis import given
from hypothesis.strategies import dictionaries, sampled_from, text
from pytest import mark
from wandb._pydantic import IS_PYDANTIC_V2
from wandb.automations import ActionType, SendNotification, SendWebhook
from wandb.automations._generated import AlertSeverity, TriggeredActionType
from wandb.sdk.wandb_alerts import AlertLevel

from ._strategies import gql_ids, jsonables, printable_text

VALID_ALERT_SEVERITY_ARG_VALUES = (
    # Where possible, accept both enum and (case-insensitive) string types for `severity`.
    *AlertSeverity,
    *AlertLevel,
    *(e.value.upper() for e in AlertSeverity),
    *(e.value.lower() for e in AlertSeverity),
)


def test_public_action_type_enum_matches_generated():
    """Check that the public `ActionType` enum is a subset of the schema-generated enum.

    This is a safeguard in case we've had to make any extra customizations
    (e.g. renaming members) to the public API definition.
    """
    public_enum_values = {e.value for e in ActionType}
    generated_enum_values = {e.value for e in TriggeredActionType}
    assert public_enum_values <= generated_enum_values


@mark.skipif(
    not IS_PYDANTIC_V2,
    reason="Unsupported in Pydantic v1: non-essential enhancement",
)
@given(
    integration_id=gql_ids(prefix="Integration"),
    title=printable_text,
    message=printable_text,
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
