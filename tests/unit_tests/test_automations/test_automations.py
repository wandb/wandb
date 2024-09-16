from base64 import b64encode

from wandb.sdk import automations
from wandb.sdk.automations import NewAutomation, Severity, actions, events
from wandb.sdk.automations.generated.schema_gen import ArtifactCollection


def test_define_automation():
    # TODO: Fix this
    collection = ArtifactCollection.construct(id=b64encode(b"fake-collection-id"))

    event = automations.on(events.LINK_ARTIFACT, collection)

    # TODO: Fix this
    action = actions.NewNotificationActionInput(
        integration_id=b64encode(b"fake-integration-id"),
        title="It's done!",
        message="Programmatic API test successful!",
        severity=Severity.INFO,
    )

    new_automation = automations.define(
        (event >> action),
        name="Testing programmatic automations API",
        description="longer description here",
        enabled=True,
    )
    assert isinstance(new_automation, NewAutomation)
