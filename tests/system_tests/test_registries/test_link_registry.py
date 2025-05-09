from __future__ import annotations

from dataclasses import dataclass

import pytest
import wandb
from wandb.proto import wandb_internal_pb2 as pb


@dataclass
class LinkArtifactExpectation:
    entity: str = ""
    org: str = ""
    project: str = ""
    collection: str = ""


@pytest.mark.parametrize(
    (
        "link_artifact_path",
        "expected",
    ),
    (
        (
            "org-name/wandb-registry-model/test-collection",
            LinkArtifactExpectation(
                org="org-name",
                project="wandb-registry-model",
                collection="test-collection",
            ),
        ),
        (
            "org-entity-name/wandb-registry-model/test-collection",
            LinkArtifactExpectation(
                org="org-entity-name",
                project="wandb-registry-model",
                collection="test-collection",
            ),
        ),
        (
            "wandb-registry-model/test-collection",
            LinkArtifactExpectation(
                project="wandb-registry-model",
                collection="test-collection",
            ),
        ),
        (
            "random-entity/not-registry/test-collection",
            LinkArtifactExpectation(
                entity="random-entity",
                project="not-registry",
                collection="test-collection",
            ),
        ),
        (
            "not-registry/test-collection",
            LinkArtifactExpectation(
                project="not-registry",
                collection="test-collection",
            ),
        ),
    ),
)
def test_link_artifact_client_handles_registry_paths(
    tmp_path,
    user,
    api,
    link_artifact_path,
    expected,
    mocker,
):
    # Tests link_artifact for registry paths correctly passes in
    # the expected variables to the backend.
    project = "test"
    artifact_name = "test-artifact"
    artifact_type = "test-type"

    artifact_filepath = tmp_path / "boom.txt"
    artifact_filepath.write_text("testing")

    run = wandb.init(entity=user, project=project)
    artifact = wandb.Artifact(name=artifact_name, type=artifact_type)
    artifact.add_file(str(artifact_filepath), "test-name")

    # Assign tags when logging
    run.log_artifact(artifact)
    artifact.wait()

    mock__deliver_link_artifact = mocker.patch(
        "wandb.sdk.interface.interface_shared.InterfaceShared._deliver_link_artifact"
    )

    # Link the artifact
    run.link_artifact(artifact, link_artifact_path)
    link_artifact_request = pb.LinkArtifactRequest(
        server_id=artifact.id,
        portfolio_name=expected.collection,
        portfolio_aliases=[],
        portfolio_entity=expected.entity or user,
        portfolio_project=expected.project,
        portfolio_organization=expected.org,
    )
    mock__deliver_link_artifact.assert_called_once_with(link_artifact_request)

    run.finish()
