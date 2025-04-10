import json

from hypothesis import given
from hypothesis.strategies import sampled_from
from pytest import mark
from wandb._pydantic import IS_PYDANTIC_V2
from wandb.automations import DoNotification
from wandb.automations._generated import AlertSeverity
from wandb.automations.actions import DoWebhook
from wandb.sdk.wandb_alerts import AlertLevel

from ._strategies import gql_ids, printable_text

VALID_ALERT_SEVERITY_ARG_VALUES = (
    # Where possible, accept both enum and (case-insensitive) string types for `severity`.
    *AlertSeverity,
    *AlertLevel,
    *(e.value.upper() for e in AlertSeverity),
    *(e.value.lower() for e in AlertSeverity),
)


@mark.skipif(
    not IS_PYDANTIC_V2,
    reason="Unsupported in Pydantic v1: non-essential enhancement",
)
@given(
    integration_id=gql_ids(),
    title=printable_text(),
    message=printable_text(),
    severity=sampled_from(VALID_ALERT_SEVERITY_ARG_VALUES),
)
def test_notification_input_action_accepts_legacy_alert_args(
    integration_id, title, message, severity
):
    """Notification actions accept legacy `wandb.Alert` kwargs for continuity/convenience."""

    # Instantiate directly by the actual field names
    from_normal_args = DoNotification(
        integration_id=integration_id,
        title=title,
        message=message,
        severity=severity,
    )

    # Instantiate by the legacy wandb.Alert arg names
    from_legacy_args = DoNotification(
        integration_id=integration_id,
        title=title,
        text=message,
        level=severity,
    )

    assert from_legacy_args == from_normal_args
    assert from_legacy_args.model_dump() == from_normal_args.model_dump()
    assert from_legacy_args.model_dump_json() == from_normal_args.model_dump_json()


def test_webhook_input_action_accepts_deserialized_payload(integration_id):
    """Notification actions accept legacy `wandb.Alert` kwargs for continuity/convenience."""

    payload = {"test": "test"}

    # Instantiate directly by the actual field names
    webhook_action = DoWebhook(
        integration_id=integration_id,
        request_payload=payload,
    )

    assert webhook_action.request_payload == payload

    webhook_action_dict = webhook_action.model_dump()
    assert isinstance(webhook_action_dict["requestPayload"], str)
    assert json.loads(webhook_action_dict["requestPayload"]) == payload
