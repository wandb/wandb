from hypothesis import given
from hypothesis.strategies import sampled_from
from wandb.sdk.automations import DoNotification
from wandb.sdk.automations._generated import AlertSeverity
from wandb.sdk.wandb_alerts import AlertLevel

from ._strategies import gql_ids, printable_text


@given(
    integration_id=gql_ids(),
    title=printable_text(),
    message=printable_text(),
    severity=sampled_from(
        (
            *AlertSeverity,
            *AlertLevel,
            *(e.value for e in AlertSeverity),
            *(e.value.lower() for e in AlertSeverity),
        )
    ),
)
def test_notification_actions_accept_legacy_alert_args(
    integration_id, title, message, severity
):
    """Notification actions accept legacy `wandb.Alert` kwargs for continuity/convenience."""

    action = DoNotification(
        integration_id=integration_id,
        title=title,
        message=message,
        severity=severity,
    )
    action_from_legacy_argnames = DoNotification(
        integration_id=integration_id,
        title=title,
        text=message,
        level=severity,
    )

    assert action_from_legacy_argnames == action
    assert action_from_legacy_argnames.model_dump_json() == action.model_dump_json()
