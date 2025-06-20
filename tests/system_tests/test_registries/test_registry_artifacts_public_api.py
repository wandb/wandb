from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import wandb
from wandb.apis.public.registries._utils import fetch_org_entity_from_organization
from wandb.apis.public.registries.registry import Registry
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.util import random_string

if TYPE_CHECKING:
    from ..backend_fixtures import TeamAndOrgNames


@pytest.fixture(scope="function")
def api(user, team_and_org: TeamAndOrgNames) -> wandb.Api:
    return wandb.Api(
        overrides={"organization": team_and_org.org, "entity": team_and_org.team}
    )


@pytest.fixture(scope="function")
def org_entity(api: wandb.Api, org: str) -> str:
    if not InternalApi()._server_supports(ServerFeature.ARTIFACT_REGISTRY_SEARCH):
        pytest.skip("Cannot fetch org entity on this server version.")
    return fetch_org_entity_from_organization(api.client, org)


@pytest.fixture(scope="function")
def registry(api: wandb.Api, org: str) -> Registry:
    # Full name will be "wandb-registry-model"
    return api.create_registry("model", visibility="organization", organization=org)


@pytest.fixture(scope="function")
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


@pytest.fixture(scope="function")
def target_collection_name(worker_id: str) -> str:
    return f"collection-{worker_id}-{random_string(8)}"


@pytest.fixture
def linked_artifact(
    source_artifact: Artifact,
    registry: Registry,
    target_collection_name: str,
    org_entity: str,
) -> str:
    return source_artifact.link(
        f"{org_entity}/{registry.full_name}/{target_collection_name}"
    )


def test_fetch_registry_artifact(
    user,
    api: wandb.Api,
    org: str,
    org_entity: str,
    registry: Registry,
    linked_artifact: Artifact,
    target_collection_name: str,
    source_artifact: Artifact,
):
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
