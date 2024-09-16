from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.interface.interface import InterfaceBase


def test_link_artifact_registry_orgname(mocker, monkeypatch, wandb_init, user):
    # interface = InterfaceBase()
    spy = mocker.spy(InterfaceBase, "deliver_link_artifact")

    artifact = Artifact("foo", type="any")

    # Call the method
    run = wandb_init(entity=user)
    run.log_artifact(artifact).wait()
    run.link_artifact(
        artifact,
        "org-entity/wandb-registry-project/portfolio-name",
    )

    # # Assertions
    assert spy.call_count == 1
    assert spy.call_args.args[3] == "portfolio-name"
    assert spy.call_args.args[5] == ""  # entity should be empty for registry artifacts
    assert spy.call_args.args[6] == "wandb-registry-project"
    assert (
        spy.call_args.args[7] == "org-entity"
    )  # organization should be set to the original entity for registry artifacts
