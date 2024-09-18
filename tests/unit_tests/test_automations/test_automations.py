from base64 import b64encode

from pytest import fixture
from pydantic import Base64Encoder

from wandb.sdk import automations
from wandb.sdk.automations import NewAutomation, Severity, actions, events, scopes
from wandb.sdk.automations.schemas_gen import (
    CreateFilterTriggerInput,
)

fake_artifact_collection = scopes.ArtifactCollectionScope(
    id=Base64Encoder.encode(b"fake-collection-id")
)
fake_project = scopes.ProjectScope(id=Base64Encoder.encode(b"fake-project-id"))


@fixture
def artifact_collection() -> scopes.ArtifactCollectionScope:
    # TODO: Fix this
    return fake_artifact_collection


def test_define_automation__link_artifact(artifact_collection):
    event = automations.on(events.LINK_ARTIFACT, artifact_collection)

    # TODO: Fix this -- is there a way to avoid specifying integration_id?
    action = actions.NewNotification(
        integration_id=Base64Encoder.encode(b"fake-integration-id"),
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

    # Check that this we can produce a valid GraphQL input for creating an automation
    request_payload = new_automation.to_create_payload()
    validated_payload = CreateFilterTriggerInput.model_validate(request_payload)

    assert (
        validated_payload.model_dump()
        == {
            "__typename": "CreateFilterTriggerInput",
            "clientMutationId": None,
            "description": "longer description here",
            "enabled": True,
            "eventFilter": '{"filter":"{\\"$or\\":[{\\"$and\\":[]}]}"}',
            "name": "Testing programmatic automations API",
            "scopeID": "ZmFrZS1jb2xsZWN0aW9uLWlk\n",
            "scopeType": "ARTIFACT_COLLECTION",
            "triggeredActionConfig": {
                "__typename": "TriggeredActionConfig",
                "genericWebhookActionInput": None,
                "notificationActionInput": {
                    "__typename": "NotificationActionInput",
                    "integrationID": "ZmFrZS1pbnRlZ3JhdGlvbi1pZA==\n",
                    "message": "Programmatic " "API test " "successful!",
                    "severity": "INFO",
                    "title": "It's done!",
                },
                "queueJobActionInput": None,
            },
            "triggeredActionType": "NOTIFICATION",
            "triggeringEventType": "LINK_MODEL",
        }
        != {
            "clientMutationId": None,
            "description": "longer description here",
            "enabled": True,
            "eventFilter": '{"filter":"{\\"$or\\":[{\\"$and\\":[]}]}"}',
            "name": "Testing programmatic automations API",
            "scopeID": "ZmFrZS1jb2xsZWN0aW9uLWlk\n",
            "scopeType": "ARTIFACT_COLLECTION",
            "triggeredActionConfig": {},
            "triggeredActionType": "NOTIFICATION",
            "triggeringEventType": "LINK_MODEL",
        }
    )


def test_define_automation__add_artifact_alias(artifact_collection):
    event = automations.on(
        events.ADD_ARTIFACT_ALIAS,
        scope=artifact_collection,
        alias="test-alias",
    )

    # TODO: Fix this -- is there a way to avoid specifying integration_id?
    action = actions.NewNotification(
        integration_id=Base64Encoder.encode(b"fake-integration-id"),
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

    # Check that this we can produce a valid GraphQL input for creating an automation
    request_payload = new_automation.to_create_payload()
    validated_payload = CreateFilterTriggerInput.model_validate(request_payload)

    assert validated_payload.model_dump() == {
        "__typename": "CreateFilterTriggerInput",
        "clientMutationId": None,
        "description": "longer description here",
        "enabled": True,
        "eventFilter": '{"filter":"{\\"alias\\":{\\"$regex\\":\\"test-alias\\",\\"$options\\":null}}"}',
        "name": "Testing programmatic automations API",
        "scopeID": "ZmFrZS1jb2xsZWN0aW9uLWlk\n",
        "scopeType": "ARTIFACT_COLLECTION",
        "triggeredActionConfig": {
            "__typename": "TriggeredActionConfig",
            "genericWebhookActionInput": None,
            "notificationActionInput": {
                "__typename": "NotificationActionInput",
                "integrationID": "ZmFrZS1pbnRlZ3JhdGlvbi1pZA==\n",
                "message": "Programmatic " "API test " "successful!",
                "severity": "INFO",
                "title": "It's done!",
            },
            "queueJobActionInput": None,
        },
        "triggeredActionType": "NOTIFICATION",
        "triggeringEventType": "ADD_ARTIFACT_ALIAS",
    }


def test_define_automation__create_artifact(artifact_collection):
    event = automations.on(
        events.CREATE_ARTIFACT,
        scope=artifact_collection,
    )

    # TODO: Fix this -- is there a way to avoid specifying integration_id?
    action = actions.NewNotification(
        integration_id=Base64Encoder.encode(b"fake-integration-id"),
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

    # Check that this we can produce a valid GraphQL input for creating an automation
    request_payload = new_automation.to_create_payload()
    validated_payload = CreateFilterTriggerInput.model_validate(request_payload)

    assert validated_payload.model_dump() == {
        "__typename": "CreateFilterTriggerInput",
        "clientMutationId": None,
        "description": "longer description here",
        "enabled": True,
        "eventFilter": '{"filter":"{\\"$or\\":[{\\"$and\\":[]}]}"}',
        "name": "Testing programmatic automations API",
        "scopeID": "ZmFrZS1jb2xsZWN0aW9uLWlk\n",
        "scopeType": "ARTIFACT_COLLECTION",
        "triggeredActionConfig": {
            "__typename": "TriggeredActionConfig",
            "genericWebhookActionInput": None,
            "notificationActionInput": {
                "__typename": "NotificationActionInput",
                "integrationID": "ZmFrZS1pbnRlZ3JhdGlvbi1pZA==\n",
                "message": "Programmatic " "API test " "successful!",
                "severity": "INFO",
                "title": "It's done!",
            },
            "queueJobActionInput": None,
        },
        "triggeredActionType": "NOTIFICATION",
        "triggeringEventType": "CREATE_ARTIFACT",
    }
