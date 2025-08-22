from __future__ import annotations

from urllib.parse import quote

import wandb
from wandb import Api, Artifact, util
from wandb.apis.public.registries.registry import Registry
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.internal.internal_api import Api as InternalApi


def test_fetch_migrated_registry_artifact(
    user,
    api,
    mocker,
    capsys,
):
    mocker.patch(
        "wandb.sdk.artifacts.artifact.Artifact._from_attrs",
    )
    mock_fetch_artifact_by_name = mocker.patch.object(api.client, "execute")

    mock_artifact_fragment_data = {
        "name": "test-collection",  # NOTE: relevant
        "versionIndex": 0,  # NOTE: relevant
        # ------------------------------------------------------------------------------
        # NOTE: Remaining artifact fields are placeholders and not as relevant to the test
        "artifactType": {
            "name": "model",
        },
        "artifactSequence": {
            "id": "PLACEHOLDER",
            "name": "test-collection",
            "project": {
                "id": "PLACEHOLDER",
                "entityName": "test-team",
                "name": "orig-project",
            },
        },
        "id": "PLACEHOLDER",
        "description": "PLACEHOLDER",
        "metadata": "{}",
        "state": "COMMITTED",
        "currentManifest": None,
        "fileCount": 0,
        "commitHash": "PLACEHOLDER",
        "createdAt": "PLACEHOLDER",
        "updatedAt": None,
        # ------------------------------------------------------------------------------
    }

    # Mock the GQL response to return the version in the new org registry
    mock_fetch_artifact_by_name.return_value = {
        "project": {
            "artifact": mock_artifact_fragment_data,
            "artifactCollectionMembership": {
                "id": "PLACEHOLDER",
                "artifact": mock_artifact_fragment_data,
                "artifactCollection": {
                    "__typename": "ArtifactPortfolio",
                    "id": "PLACEHOLDER",
                    "name": "test-collection",  # NOTE: relevant
                    "project": {
                        "id": "PLACEHOLDER",
                        "entityName": "org-entity-name",  # NOTE: relevant
                        "name": "wandb-registry-model",  # NOTE: relevant
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
        base_url = util.app_url(run.settings.base_url)
        linked_artifact = run.link_artifact(
            source_artifact, f"{registry.full_name}/{target_collection_name}"
        )
        collection_path = f"{org_entity}/{registry.full_name}/{target_collection_name}"
        encoded_selection_path = quote(collection_path, safe="")

        expected_url = f"{base_url}/orgs/{org}/registry/{registry.name}?selectionPath={encoded_selection_path}&view=membership&version={linked_artifact.version}"

        assert linked_artifact.url == expected_url
