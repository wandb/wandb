from __future__ import annotations

from typing import Any
from urllib.parse import quote

import wandb
from pytest import fixture
from wandb import Api, Artifact
from wandb._strutils import nameof
from wandb.apis.public.registries.registry import Registry
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.artifacts._generated import (
    ArtifactByName,
    ArtifactFragment,
    ArtifactMembershipByName,
    ArtifactMembershipFragment,
)
from wandb.sdk.artifacts._gqlutils import server_supports


@fixture
def mock_artifact_fragment_data() -> dict[str, Any]:
    fragment = ArtifactFragment(
        name="test-collection",  # NOTE: relevant
        version_index=0,  # NOTE: relevant
        artifact_type={"name": "model"},
        artifact_sequence={
            "name": "test-collection",
            "project": {
                "name": "orig-project",
                "entity": {"name": "test-team"},
            },
        },
        id="PLACEHOLDER",
        description="PLACEHOLDER",
        tags=[],
        ttl_duration_seconds=-2,
        ttl_is_inherited=False,
        metadata="{}",
        state="COMMITTED",
        size=0,
        digest="FAKE_DIGEST",
        file_count=0,
        commit_hash="PLACEHOLDER",
        created_at="PLACEHOLDER",
        updated_at=None,
        history_step=None,
    )
    return fragment.model_dump()


@fixture
def mock_membership_fragment_data(
    mock_artifact_fragment_data: dict[str, Any],
) -> dict[str, Any]:
    fragment = ArtifactMembershipFragment(
        id="PLACEHOLDER",
        artifact=mock_artifact_fragment_data,
        artifactCollection={
            "__typename": "ArtifactPortfolio",
            "name": "test-collection",  # NOTE: relevant
            "project": {
                "name": "wandb-registry-model",  # NOTE: relevant
                "entity": {"name": "org-entity-name"},  # NOTE: relevant
            },
        },
        versionIndex=1,
        aliases=[
            {"id": "PLACEHOLDER", "alias": "my-alias"},
        ],
    )
    return fragment.model_dump()


@fixture
def mock_artifact_rsp_data(
    mock_artifact_fragment_data: dict[str, Any],
) -> dict[str, Any]:
    """Return the mocked response for the GQL ArtifactByName query."""
    return {
        "data": {
            "project": {
                "artifact": mock_artifact_fragment_data,
            }
        }
    }


@fixture
def mock_membership_rsp_data(
    mock_membership_fragment_data: dict[str, Any],
) -> dict[str, Any]:
    """Return the mocked response for the GQL ArtifactMembershipByName query."""
    return {
        "data": {
            "project": {
                "artifactCollectionMembership": mock_membership_fragment_data,
            }
        }
    }


def test_fetch_migrated_registry_artifact(
    user,
    wandb_backend_spy,
    api,
    mocker,
    capsys,
    mock_artifact_rsp_data: dict[str, Any],
    mock_membership_rsp_data: dict[str, Any],
):
    server_supports_artifact_via_membership = server_supports(
        api.client, ServerFeature.PROJECT_ARTIFACT_COLLECTION_MEMBERSHIP
    )

    mocker.patch("wandb.sdk.artifacts.artifact.Artifact._from_attrs")

    # Setup: Stub the appropriate GQL response (depending on server version)
    # to return the artifact in the new org registry
    if server_supports_artifact_via_membership:
        op_name = nameof(ArtifactMembershipByName)
        mock_rsp = wandb_backend_spy.gql.Constant(content=mock_membership_rsp_data)
    else:
        op_name = nameof(ArtifactByName)
        mock_rsp = wandb_backend_spy.gql.Constant(content=mock_artifact_rsp_data)

    wandb_backend_spy.stub_gql(
        match=wandb_backend_spy.gql.Matcher(operation=op_name),
        respond=mock_rsp,
    )

    # Fetching an artifact from the legacy model registry
    api.artifact("test-team/model-registry/test-collection:v0")

    assert mock_rsp.total_calls == 1

    captured = capsys.readouterr()
    if server_supports_artifact_via_membership:
        assert (
            "This model registry has been migrated and will be discontinued"
            in captured.err
        )


def test_registry_artifact_url(
    team: str,
    api: Api,
    org: str,
    org_entity: str,
    registry: Registry,
    source_artifact: Artifact,
    target_collection_name: str,
):
    with wandb.init() as run:
        linked_artifact = run.link_artifact(
            source_artifact, f"{registry.full_name}/{target_collection_name}"
        )
        collection_path = f"{org_entity}/{registry.full_name}/{target_collection_name}"
        encoded_selection_path = quote(collection_path, safe="")

        expected_url = (
            f"{run.settings.app_url}/orgs/{org}/registry/{registry.name}"
            f"?selectionPath={encoded_selection_path}"
            "&view=membership"
            f"&version={linked_artifact.version}"
        )

        assert linked_artifact.url == expected_url
