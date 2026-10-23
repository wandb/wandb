"""Tests for lazy membership-aliases pagination in `Artifact._update()`.

`UpdateArtifact` can return `artifactMembership` directly, and that
membership's `aliasesConnection` lets the SDK fetch only the first page of
aliases instead of the unbounded flat `aliases` field -- mirroring the
`ArtifactMembershipByName` pagination covered in
`tests/unit_tests/test_artifacts/test_artifact_from_name.py`. This test uses
the real create/commit/save flow against the local test backend and stubs
only `ServerFeaturesQuery` and the `UpdateArtifact` mutation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import wandb
from pytest import mark

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
    aliases_connection: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": membership_id,
        "versionIndex": version_index,
        "createdAt": "2026-01-01T00:00:00Z",
        "artifactCollection": _collection_dict(
            entity=entity, project=project, collection=collection
        ),
        "artifact": artifact,
        "aliasesConnection": aliases_connection,
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


@mark.parametrize("pagination_enabled", [True, False])
def test_update_resolves_membership_aliases(
    user, wandb_backend_spy: WandbBackendSpy, pagination_enabled: bool
):
    gql = wandb_backend_spy.gql

    # `feature_enabled()` caches the server's feature map for the sidecar's
    # lifetime, keyed by whichever call triggers the first load -- stub
    # before anything can trigger that, not right before `.save()`.
    _stub_server_features(
        wandb_backend_spy,
        pagination_enabled=pagination_enabled,
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
    if pagination_enabled:
        membership = _membership_dict(
            membership_id="membership-id",
            entity=entity,
            project=project,
            collection=collection,
            version_index=5,
            artifact=bare_artifact_dict,
            aliases_connection=_aliases_connection(["first-page"], has_next_page=True),
        )
    else:
        membership = {
            "id": "membership-id",
            "versionIndex": 5,
            "createdAt": "2026-01-01T00:00:00Z",
            "aliases": [{"id": "alias-flat", "alias": "flat-alias"}],
            "artifactCollection": _collection_dict(
                entity=entity, project=project, collection=collection
            ),
            "artifact": bare_artifact_dict,
        }

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

    continuation_response = gql.Constant(
        content={
            "data": {
                "project": {
                    "artifactCollectionMembership": {
                        "aliasesConnection": _aliases_connection(
                            ["second-page"], has_next_page=False
                        )
                    }
                }
            },
        }
    )
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ArtifactMembershipAliases"), continuation_response
    )

    artifact.description = "updated description"
    artifact.save()

    assert update_response.total_calls == 1
    sent_query = update_response.requests[0].query
    assert artifact.version == "v5"

    if pagination_enabled:
        assert "aliasesConnection" in sent_query
        assert "aliases {" not in sent_query
        assert continuation_response.total_calls == 0

        assert set(artifact.aliases) == {"first-page", "second-page"}
        assert continuation_response.total_calls == 1

        # A second read doesn't re-fetch anything.
        assert set(artifact.aliases) == {"first-page", "second-page"}
        assert continuation_response.total_calls == 1
    else:
        assert "aliasesConnection" not in sent_query
        assert "flat-alias" in artifact.aliases
        assert continuation_response.total_calls == 0
