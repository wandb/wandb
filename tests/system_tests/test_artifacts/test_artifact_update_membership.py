"""Tests for Artifact._update()'s use of the artifactMembership payload field.

`updateArtifact` can return `artifactMembership` directly, letting
`Artifact._assign_attrs` resolve version/aliases from the single membership
instead of falling back to the artifact-wide `aliases` field (which fans out
across every collection the artifact belongs to). These tests cover both
sides of that branch: the ARTIFACT_MEMBERSHIP_ON_ARTIFACT_PAYLOAD feature
being enabled and disabled, using the real create/commit flow against the
local test backend and stubbing only ServerFeaturesQuery and UpdateArtifact.
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


def _alias_dict(
    alias: str, *, entity: str, project: str, collection: str
) -> dict[str, Any]:
    return {
        "id": f"alias-{alias}",
        "alias": alias,
        "artifactCollection": _collection_dict(
            entity=entity, project=project, collection=collection
        ),
    }


def _artifact_fragment_dict(
    *,
    artifact_id: str,
    entity: str,
    project: str,
    collection: str,
    version_index: int,
    aliases: list[str],
) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "artifactSequence": {
            "name": collection,
            "project": _project_dict(entity=entity, project=project),
        },
        "versionIndex": version_index,
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
        "aliases": [
            _alias_dict(a, entity=entity, project=project, collection=collection)
            for a in aliases
        ],
    }


def _membership_fragment_dict(
    *,
    membership_id: str,
    entity: str,
    project: str,
    collection: str,
    version_index: int,
    aliases: list[str],
    artifact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": membership_id,
        "versionIndex": version_index,
        "createdAt": "2026-01-01T00:00:00Z",
        "aliases": [{"id": f"alias-{a}", "alias": a} for a in aliases],
        "artifactCollection": _collection_dict(
            entity=entity, project=project, collection=collection
        ),
        "artifact": artifact,
    }


@mark.parametrize("membership_on_payload", [True, False])
def test_update_artifact_resolves_from_membership_payload(
    user,
    membership_on_payload: bool,
    wandb_backend_spy: WandbBackendSpy,
):
    gql = wandb_backend_spy.gql

    # ServiceApi.feature_enabled() loads the server's feature map once per
    # wandb-core sidecar process (on whichever call happens to trigger it
    # first) and caches it for the sidecar's lifetime; it is not re-queried
    # per call. The stub must be in place before anything in this test can
    # trigger that first load, so it's registered before wandb.init() rather
    # than right before the update() call it's actually meant to affect.
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ServerFeaturesQuery"),
        gql.Constant(
            content={
                "data": {
                    "serverInfo": {
                        "features": [
                            {
                                "name": "ARTIFACT_MEMBERSHIP_ON_ARTIFACT_PAYLOAD",
                                "isEnabled": membership_on_payload,
                            },
                        ],
                    },
                },
            }
        ),
    )

    # Log a real artifact through the normal create/commit flow (unstubbed,
    # hits the real local backend) so it has a genuine id/collection to
    # update against.
    with wandb.init() as run:
        artifact = wandb.Artifact("my-update-membership-artifact", type="dataset")
        with artifact.new_file("x.txt", "w") as f:
            f.write("hello")
        run.log_artifact(artifact)
        artifact.wait()

    artifact_id = artifact.id
    entity = artifact.entity
    project = artifact.project
    collection = artifact.name.split(":")[0]

    # The membership's aliases/versionIndex deliberately differ from the bare
    # artifact's, so the assertions can tell which one the SDK actually used.
    bare_artifact_dict = _artifact_fragment_dict(
        artifact_id=artifact_id,
        entity=entity,
        project=project,
        collection=collection,
        version_index=1,
        aliases=["from-artifact"],
    )
    update_response = gql.Constant(
        content={
            "data": {
                "result": {
                    "artifact": bare_artifact_dict,
                    **(
                        {
                            "artifactMembership": _membership_fragment_dict(
                                membership_id="membership-id",
                                entity=entity,
                                project=project,
                                collection=collection,
                                version_index=5,
                                aliases=["from-membership"],
                                artifact=bare_artifact_dict,
                            )
                        }
                        if membership_on_payload
                        else {}
                    ),
                },
            },
        }
    )
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="UpdateArtifact"),
        update_response,
    )

    artifact.description = "updated description"
    artifact.save()

    assert update_response.total_calls == 1
    sent_query = update_response.requests[0].query
    if membership_on_payload:
        assert "artifactMembership" in sent_query
        assert artifact.version == "v5"
        assert "from-membership" in artifact.aliases
        assert "from-artifact" not in artifact.aliases
    else:
        assert "artifactMembership" not in sent_query
        assert artifact.version == "v1"
        assert "from-artifact" in artifact.aliases
