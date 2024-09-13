from pytest import fixture

from wandb import Artifact
from wandb.sdk import automations
from wandb.sdk.automations.actions import AlertSeverity, NotificationActionInput
from wandb.sdk.automations.events import LinkArtifactInput


@fixture
def collection_name(wandb_init) -> str:
    return "test-automations-api-collection"


@fixture
def artifact(tmp_path, wandb_init, collection_name, api) -> Artifact:
    with wandb_init() as run:
        artifact_filepath = tmp_path / "test-artifact.txt"
        artifact_filepath.write_text("hello world")
        artifact = Artifact("testing", "dataset")
        artifact.add_file(artifact_filepath)

        logged_artifact: Artifact = run.log_artifact(artifact)
        logged_artifact.link(collection_name)

        # collection = ArtifactCollection(
        #     api.client,
        #     run.entity,
        #     run.project,
        #     collection_name,
        #     "dataset",
        # )
        # collection.save()
        # logged_artifact.link(collection.name)

        logged_artifact.wait()

    return logged_artifact


def test_list_automations(user, api):
    triggers = list(automations.query(api.client))
    assert triggers == []


def test_create_automation(user, api, artifact, collection_name):
    collection = api.artifact_collection("dataset", name=collection_name)

    event = LinkArtifactInput(scope=collection)
    action = NotificationActionInput(
        integration_id="SW50ZWdyYXRpb246MTA1NTc=\\n",
        title="It's done!",
        message="Programmatic API test successful!",
        severity=AlertSeverity.INFO,
    )

    new_automation = automations.create(
        api.client,
        (event >> action),
        name="Testing programmatic automations API",
        description="longer description here",
        enabled=True,
    )

    new_automation_id = new_automation.id

    current_automation_ids = set(auto.id for auto in automations.query(api.client))
    assert new_automation_id in current_automation_ids

    delete_result = automations.delete(api.client, new_automation_id)
    assert delete_result.success is True

    current_automation_ids = set(auto.id for auto in automations.query(api.client))
    assert new_automation_id not in current_automation_ids
