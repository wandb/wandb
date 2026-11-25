"""Tests for lazy membership-aliases pagination in `Artifact._update()`.

`UpdateArtifact` can return `artifactMembership` directly. Its aliases are
fetched only when requested, through the paginated connection, mirroring the
`ArtifactMembershipByName` pagination covered in
`tests/unit_tests/test_artifacts/test_artifact_from_name.py`. This test uses
the real create/commit/save flow against the local test backend and stubs
only `ServerFeaturesQuery` and the `UpdateArtifact` mutation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import wandb
from wandb.sdk.artifacts._generated import ArtifactMembershipFragment
from wandb.sdk.artifacts._validators import FullArtifactPath
from wandb.sdk.artifacts.artifact import Artifact

if TYPE_CHECKING:
    from tests.fixtures.wandb_backend_spy import WandbBackendSpy


def _project_dict(*, entity: str, project: str) -> dict[str, Any]:
    return {
        "id": "project-id",
        "internalId": "1",
        "name": project,
        "entity": {"name": entity},
    }


def _collection_dict(*, entity: str, project: str, collection: str) -> dict[str, Any]:
    return {
        "__typename": "ArtifactSequence",
        "name": collection,
        "project": _project_dict(entity=entity, project=project),
    }


def _artifact_fragment_dict(
    *, artifact_id: str, entity: str, project: str, collection: str
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "artifactSequence": {
            "name": collection,
            "project": _project_dict(entity=entity, project=project),
        },
        "versionIndex": 0,
        "artifactType": {"name": "dataset"},
        "description": None,
        "metadata": None,
        "ttlDurationSeconds": -1,
        "ttlIsInherited": True,
        "tags": [],
        "historyStep": None,
        "state": "COMMITTED",
        "size": 0,
        "digest": "abc123",
        "commitHash": None,
        "fileCount": 0,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": None,
    }


def _aliases_connection(aliases: list[str], *, has_next_page: bool) -> dict[str, Any]:
    return {
        "pageInfo": {
            "hasNextPage": has_next_page,
            "endCursor": "cursor-1" if has_next_page else None,
        },
        "edges": [{"node": {"id": f"alias-{a}", "alias": a}} for a in aliases],
    }


def _membership_dict(
    *,
    membership_id: str,
    entity: str,
    project: str,
    collection: str,
    version_index: int,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": membership_id,
        "versionIndex": version_index,
        "createdAt": "2026-01-01T00:00:00Z",
        "artifactCollection": _collection_dict(
            entity=entity, project=project, collection=collection
        ),
        "artifact": artifact,
    }


def _stub_server_features(
    wandb_backend_spy: WandbBackendSpy, *, pagination_enabled: bool, **extra_features
):
    gql = wandb_backend_spy.gql
    features = [
        {
            "name": "ARTIFACT_MEMBERSHIP_ALIASES_PAGINATION",
            "isEnabled": pagination_enabled,
        }
    ]
    features += [
        {"name": name, "isEnabled": enabled} for name, enabled in extra_features.items()
    ]
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ServerFeaturesQuery"),
        gql.Constant(content={"data": {"serverInfo": {"features": features}}}),
    )


def test_update_defers_membership_aliases(user, wandb_backend_spy: WandbBackendSpy):
    gql = wandb_backend_spy.gql

    # `feature_enabled()` caches the server's feature map for the sidecar's
    # lifetime, keyed by whichever call triggers the first load -- stub
    # before anything can trigger that, not right before `.save()`.
    _stub_server_features(
        wandb_backend_spy,
        pagination_enabled=True,
        ARTIFACT_MEMBERSHIP_ON_ARTIFACT_PAYLOAD=True,
    )

    with wandb.init() as run:
        artifact = wandb.Artifact("my-update-pagination-artifact", type="dataset")
        with artifact.new_file("x.txt", "w") as f:
            f.write("hello")
        run.log_artifact(artifact)
        artifact.wait()

    entity, project = artifact.entity, artifact.project
    collection = artifact.name.split(":")[0]

    bare_artifact_dict = _artifact_fragment_dict(
        artifact_id=artifact.id, entity=entity, project=project, collection=collection
    )
    membership = _membership_dict(
        membership_id="membership-id",
        entity=entity,
        project=project,
        collection=collection,
        version_index=5,
        artifact=bare_artifact_dict,
    )

    update_response = gql.Constant(
        content={
            "data": {
                "result": {
                    "artifact": bare_artifact_dict,
                    "artifactMembership": membership,
                },
            },
        }
    )
    wandb_backend_spy.stub_gql(gql.Matcher(operation="UpdateArtifact"), update_response)

    aliases_response = gql.Constant(
        content={
            "data": {
                "project": {
                    "artifactCollectionMembership": {
                        "aliasesConnection": _aliases_connection(
                            ["first-page", "second-page"], has_next_page=False
                        )
                    }
                }
            },
        }
    )
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ArtifactMembershipAliases"), aliases_response
    )

    # Simulate an artifact fetched from a paginated membership whose aliases
    # have not yet been read.
    artifact._aliases = None
    artifact._saved_aliases = None

    artifact.description = "updated description"
    artifact.save()

    assert update_response.total_calls == 1
    sent_query = update_response.requests[0].query
    assert artifact.version == "v5"
    assert "aliases @include(if: true)" not in sent_query
    assert "$includeAliases" not in sent_query
    assert aliases_response.total_calls == 0

    assert set(artifact.aliases) == {"first-page", "second-page"}
    assert aliases_response.total_calls == 1

    # Loaded aliases stay cached through another metadata-only save.
    artifact.description = "updated again"
    artifact.save()
    assert update_response.total_calls == 2
    assert set(artifact.aliases) == {"first-page", "second-page"}
    assert aliases_response.total_calls == 1


def test_update_keeps_aliases_when_membership_missing(
    user, wandb_backend_spy: WandbBackendSpy
):
    gql = wandb_backend_spy.gql
    _stub_server_features(
        wandb_backend_spy,
        pagination_enabled=True,
        ARTIFACT_MEMBERSHIP_ON_ARTIFACT_PAYLOAD=True,
    )

    with wandb.init() as run:
        artifact = wandb.Artifact("my-update-null-membership", type="dataset")
        with artifact.new_file("x.txt", "w") as f:
            f.write("hello")
        run.log_artifact(artifact)
        artifact.wait()

    collection = artifact.name.split(":")[0]
    update_response = gql.Constant(
        content={
            "data": {
                "result": {
                    "artifact": _artifact_fragment_dict(
                        artifact_id=artifact.id,
                        entity=artifact.entity,
                        project=artifact.project,
                        collection=collection,
                    ),
                    "artifactMembership": None,
                },
            },
        }
    )
    wandb_backend_spy.stub_gql(gql.Matcher(operation="UpdateArtifact"), update_response)
    aliases_response = gql.Constant(
        content={
            "data": {
                "project": {
                    "artifactCollectionMembership": {
                        "aliasesConnection": _aliases_connection(
                            ["from-server"], has_next_page=False
                        )
                    }
                }
            },
        }
    )
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ArtifactMembershipAliases"), aliases_response
    )

    artifact._aliases = ["known"]
    artifact._saved_aliases = ["known"]
    artifact.description = "updated description"
    artifact.save()

    assert update_response.total_calls == 1
    assert "$includeAliases" not in update_response.requests[0].query
    assert artifact.aliases == ["known"]
    assert aliases_response.total_calls == 0


@pytest.mark.parametrize("pagination_enabled", [True, False])
def test_linked_save_keeps_portfolio_version_and_aliases(
    user, wandb_backend_spy: WandbBackendSpy, pagination_enabled: bool
):
    gql = wandb_backend_spy.gql
    _stub_server_features(
        wandb_backend_spy,
        pagination_enabled=pagination_enabled,
        ARTIFACT_MEMBERSHIP_ON_ARTIFACT_PAYLOAD=True,
    )

    with wandb.init() as run:
        source = wandb.Artifact("my-linked-update-source", type="dataset")
        with source.new_file("x.txt", "w") as f:
            f.write("hello")
        run.log_artifact(source)
        source.wait()

    entity, project = source.entity, source.project
    source_fragment = _artifact_fragment_dict(
        artifact_id=source.id,
        entity=entity,
        project=project,
        collection=source.name.split(":")[0],
    )
    portfolio_project = "portfolio-project"
    portfolio_collection = "portfolio-collection"
    portfolio_membership = ArtifactMembershipFragment.model_validate(
        _membership_dict(
            membership_id="portfolio-membership",
            entity=entity,
            project=portfolio_project,
            collection=portfolio_collection,
            version_index=7,
            artifact=source_fragment,
        )
    )
    linked = Artifact._from_attrs(
        FullArtifactPath(
            prefix=entity,
            project=portfolio_project,
            name=f"{portfolio_collection}:v7",
        ),
        portfolio_membership.artifact,
        source._get_service_api(),
        membership=portfolio_membership,
    )
    assert linked.is_link is True
    assert linked.version == "v7"

    read_only_response = gql.Constant(
        content={"data": {"project": {"readOnly": False}}}
    )
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="IsProjectReadOnly"), read_only_response
    )
    update_response = gql.Constant(
        content={
            "data": {
                "result": {
                    "artifact": source_fragment,
                    "artifactMembership": _membership_dict(
                        membership_id="source-membership",
                        entity=entity,
                        project=project,
                        collection=source.name.split(":")[0],
                        version_index=0,
                        artifact=source_fragment,
                    ),
                }
            }
        }
    )
    wandb_backend_spy.stub_gql(gql.Matcher(operation="UpdateArtifact"), update_response)
    aliases_response = gql.Constant(
        content={
            "data": {
                "project": {
                    "artifactCollectionMembership": {
                        "aliasesConnection": _aliases_connection(
                            ["v7", "portfolio-only"], has_next_page=False
                        )
                    }
                }
            }
        }
    )
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ArtifactMembershipAliases"), aliases_response
    )
    add_response = gql.Constant(content={"data": {"result": {"success": True}}})
    delete_response = gql.Constant(content={"data": {"result": {"success": True}}})
    wandb_backend_spy.stub_gql(gql.Matcher(operation="AddAliases"), add_response)
    wandb_backend_spy.stub_gql(gql.Matcher(operation="DeleteAliases"), delete_response)

    linked.description = "updated source description"
    linked.save()

    assert update_response.total_calls == 1
    assert linked.version == "v7"
    assert linked.linked_at == portfolio_membership.created_at
    sent_query = update_response.requests[0].query
    assert "$includeAliases" not in sent_query
    assert "artifactMembership" not in sent_query
    assert aliases_response.total_calls == 0

    assert linked.aliases == ["portfolio-only"]
    assert aliases_response.total_calls == 1
    assert aliases_response.requests[0].variables["project"] == portfolio_project
    assert aliases_response.requests[0].variables["name"] == ("portfolio-collection:v7")

    linked.aliases = ["prod"]
    linked.save()

    assert linked.version == "v7"
    assert linked.aliases == ["prod"]
    assert aliases_response.total_calls == 1
    assert update_response.total_calls == 2
    assert add_response.total_calls == 1
    assert delete_response.total_calls == 1
    for response, alias_name in (
        (add_response, "prod"),
        (delete_response, "portfolio-only"),
    ):
        alias = response.requests[0].variables["input"]["aliases"][0]
        assert alias["entityName"] == entity
        assert alias["projectName"] == portfolio_project
        assert alias["artifactCollectionName"] == portfolio_collection
        assert alias["alias"] == alias_name

    linked.save()
    assert aliases_response.total_calls == 1
    assert add_response.total_calls == 1
    assert delete_response.total_calls == 1
