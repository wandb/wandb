from __future__ import annotations

from dataclasses import dataclass

import pytest
import wandb
from wandb.apis.public.registries._utils import fetch_org_entity_from_organization
from wandb.apis.public.registries.registry import Registry
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts.artifact import Artifact


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


# TODO: Finish setting this test up
@pytest.fixture
def organization(backend_fixture_factory, user) -> str:
    """Set up backend resources for testing link_artifact within a registry."""
    return backend_fixture_factory.make_org("Test Organization", username=user)


@pytest.fixture
def org_entity(organization, api: wandb.Api) -> str:
    return fetch_org_entity_from_organization(api.client, organization)


@pytest.fixture
def registry(organization, api: wandb.Api) -> Registry:
    registry = api.create_registry(
        name="model",
        organization=organization,
        visibility="organization",
    )
    return registry


@pytest.fixture
def source_artifact(api: wandb.Api) -> Artifact:
    artifact = api.create_artifact(
        name="test-registry",
        visibility="organization",
        organization=organization,
    )
    return artifact


# def test_link_artifact_in_registry_collection(organization, org_entity, registry):
#     raise ValueError(f"{organization=}, {org_entity=}, {registry=}")
#     pass
