from __future__ import annotations

import pytest
import wandb


@pytest.mark.parametrize(
    (
        "link_artifact_path",
        "expected_entity",
        "expected_org",
        "expected_project",
        "expected_collection",
    ),
    (
        (
            "org-name/wandb-registry-model/test-collection",
            "",
            "org-name",
            "wandb-registry-model",
            "test-collection",
        ),
        (
            "org-entity-name/wandb-registry-model/test-collection",
            "",
            "org-entity-name",
            "wandb-registry-model",
            "test-collection",
        ),
        (
            "wandb-registry-model/test-collection",
            "",
            "",
            "wandb-registry-model",
            "test-collection",
        ),
        (
            "random-entity/not-registry/test-collection",
            "random-entity",
            "",
            "not-registry",
            "test-collection",
        ),
        ("not-registry/test-collection", "", "", "not-registry", "test-collection"),
    ),
)
def test_link_artifact_client_handles_registry_paths(
    tmp_path,
    user,
    wandb_init,
    api,
    link_artifact_path,
    expected_entity,
    expected_org,
    expected_collection,
    expected_project,
    mocker,
):
    project = "test"
    artifact_name = "test-artifact"
    artifact_type = "test-type"

    artifact_filepath = tmp_path / "boom.txt"
    artifact_filepath.write_text("testing")

    run = wandb_init(entity=user, project=project)
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    artifact.add_file(str(artifact_filepath), "test-name")

    # Assign tags when logging
    run.log_artifact(artifact)
    artifact.wait()

    mock_deliver_link_artifact = mocker.patch(
        "wandb.sdk.interface.interface.InterfaceBase.deliver_link_artifact"
    )

    # Link the artifact
    run.link_artifact(artifact, link_artifact_path)
    mock_deliver_link_artifact.assert_called_once()
    call_args = mock_deliver_link_artifact.call_args
    assert call_args[0][0] == run
    assert call_args[0][1] == artifact
    assert call_args[0][2] == expected_collection
    assert call_args[0][4] == expected_entity or user
    assert call_args[0][5] == expected_project
    assert call_args[0][6] == expected_org

    run.finish()
