from __future__ import annotations

import os
from typing import TYPE_CHECKING, Iterator

import pytest
import wandb
from wandb.apis.public.registries._utils import fetch_org_entity_from_organization
from wandb.apis.public.registries.registry import Registry
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.util import random_string

if TYPE_CHECKING:
    from tests.system_tests.conftest import TeamAndOrgNames


@pytest.fixture(scope="module")
def registry_user(module_mocker, backend_fixture_factory) -> Iterator[str]:
    username = backend_fixture_factory.make_user()
    envvars = {
        "WANDB_API_KEY": username,
        "WANDB_ENTITY": username,
        "WANDB_USERNAME": username,
    }
    module_mocker.patch.dict(os.environ, envvars)
    yield username


@pytest.fixture(scope="module")
def team_and_org(registry_user: str, backend_fixture_factory) -> TeamAndOrgNames:
    return backend_fixture_factory.make_team(username=registry_user)


@pytest.fixture(scope="module")
def team(team_and_org: TeamAndOrgNames) -> str:
    return team_and_org.team


@pytest.fixture(scope="module")
def org(team_and_org: TeamAndOrgNames) -> str:
    """Set up backend resources for testing link_artifact within a registry."""
    return team_and_org.org


@pytest.fixture(scope="module")
def org_entity(org: str) -> str:
    api = wandb.Api(overrides={"organization": org})
    if not InternalApi()._server_supports(ServerFeature.ARTIFACT_REGISTRY_SEARCH):
        pytest.skip("Cannot fetch org entity on this server version.")
    return fetch_org_entity_from_organization(api.client, org)


@pytest.fixture(scope="module")
def registry(org: str) -> Registry:
    api = wandb.Api(overrides={"organization": org})
    # Full name will be "wandb-registry-model"
    return api.create_registry("model", visibility="organization", organization=org)


@pytest.fixture(scope="module")
def source_artifact(team: str) -> Artifact:
    """Create a source artifact logged within a team entity.
    Log this once per module to reduce overhead for each test run.
    This should be fine as long as we're mainly testing linking functionality.
    """
    # In order to link to an org registry, the source artifact must be logged
    # within a team entity, NOT the user's personal entity.
    with wandb.init(entity=team) as run:
        artifact = wandb.Artifact(name="test-artifact", type="dataset")
        return run.log_artifact(artifact)


@pytest.fixture(scope="module")
def target_collection_name(worker_id: str) -> str:
    return f"collection-{worker_id}-{random_string(8)}"


def test_fetch_migrated_registry_artifact(
    registry_user,
    api,
    module_mocker,
    capsys,
):
    module_mocker.patch(
        "wandb.sdk.artifacts.artifact.Artifact._from_attrs",
    )
    mock_fetch_artifact_by_name = module_mocker.patch.object(api.client, "execute")

    # Mock the GQL response to return the version in the new org registry
    mock_fetch_artifact_by_name.return_value = {
        "project": {
            "artifact": {
                "name": "test-collection",
                "version": "v0",
            },
            "artifactCollectionMembership": {
                "artifact": {
                    "name": "test-collection",
                    "version": "v0",
                },
                "artifactCollection": {
                    "name": "test-collection",
                    "project": {
                        "entityName": "org-entity-name",
                        "name": "wandb-registry-model",
                    },
                },
            },
        }
    }

    # Fetching an artifact from the legacy model registry
    api.artifact("test-team/model-registry/test-collection:v0")
    mock_fetch_artifact_by_name.assert_called_once()
    captured = capsys.readouterr()
    if InternalApi()._server_supports(
        ServerFeature.PROJECT_ARTIFACT_COLLECTION_MEMBERSHIP
    ):
        assert (
            "This model registry has been migrated and will be discontinued"
            in captured.err
        )


def test_fetch_registry_artifact(
    registry_user: str,
    org: str,
    org_entity: str,
    team: str,
    registry: Registry,
    target_collection_name: str,
    source_artifact: Artifact,
):
    source_artifact.link(
        f"{org_entity}/{registry.full_name}/{target_collection_name}"
    )
    api = wandb.Api(overrides={"organization": org, "entity": team})


    artifact = api.artifact(
        f"{org}/{registry.full_name}/{target_collection_name}:latest"
    )
    assert artifact.collection is not None
    assert artifact.collection.name == target_collection_name
    assert artifact.entity == org_entity
    assert artifact.project == registry.full_name

    artifact = api.artifact(
        f"{org_entity}/{registry.full_name}/{target_collection_name}:latest"
    )
    assert artifact.collection is not None
    assert artifact.collection.name == target_collection_name
    assert artifact.entity == org_entity
    assert artifact.project == registry.full_name

    artifact = api.artifact(f"{registry.full_name}/{target_collection_name}:latest")
    assert artifact.collection is not None
    assert artifact.collection.name == target_collection_name
    assert artifact.entity == org_entity
    assert artifact.project == registry.full_name

    with pytest.raises(wandb.errors.CommError):
        artifact = api.artifact(
            f"invalid-entity/{registry.full_name}/{target_collection_name}:latest"
        )

    artifact = api.artifact(f"{source_artifact.qualified_name}")
    assert artifact.collection is not None
    assert artifact.collection.name == source_artifact.collection.name
    assert artifact.entity == source_artifact.entity
    assert artifact.project == source_artifact.project
