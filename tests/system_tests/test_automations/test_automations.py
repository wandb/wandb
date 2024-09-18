from pytest import fixture, mark
from wandb import Artifact
from wandb.apis.public import ArtifactCollection
from wandb.sdk import automations
from wandb.sdk.automations import NewAutomation
from wandb.sdk.automations.actions import NewNotification, Severity
from wandb.sdk.automations.events import LinkArtifact


@fixture
def mock_client(monkeypatch, api) -> None:
    # FIXME: HACK - patch the current client used for GQL requests in automations modules
    from wandb.sdk.automations import _utils

    def fake_client():
        return api.client

    monkeypatch.setattr(_utils, "_client", fake_client)


@fixture
def collection_name(wandb_init) -> str:
    return "test-automations-api-collection"


@fixture
def artifact(tmp_path, wandb_init, user, collection_name, api) -> Artifact:
    with wandb_init(entity=user) as run:
        artifact_filepath = tmp_path / "test-artifact.txt"
        artifact_filepath.write_text("hello world")
        artifact = Artifact("testing", "dataset")
        artifact.add_file(artifact_filepath)

        logged_artifact: Artifact = run.log_artifact(artifact)
        logged_artifact.link(collection_name)

        logged_artifact.wait()

    return logged_artifact


@fixture
def artifact_collection(api, collection_name, artifact) -> ArtifactCollection:
    return api.artifact_collection(type_name="dataset", name=collection_name)


@mark.xfail(
    reason="Getting: 'wandb.errors.UsageError: api_key not configured (no-tty). call wandb.login(key=[your_api_key])'"
)
def test_list_automations(mock_client, user):
    triggers = list(automations.get_all())
    assert triggers == []


@mark.xfail(
    reason="Getting: 'wandb.errors.UsageError: api_key not configured (no-tty). call wandb.login(key=[your_api_key])'"
)
def test_define_automation(mock_client, artifact, artifact_collection):
    event = LinkArtifact(scope=artifact_collection)
    action = NewNotification(
        integration_id="SW50ZWdyYXRpb246MTA1NTc=\\n",
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
