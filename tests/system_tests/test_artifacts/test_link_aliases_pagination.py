"""Tests for lazy membership-aliases pagination in `Artifact.link()`.

`LinkArtifact` can return `artifactMembership` directly. Its aliases are
fetched only when requested, through the paginated connection, mirroring the
`ArtifactMembershipByName` pagination covered in
`tests/unit_tests/test_artifacts/test_artifact_from_name.py`. This test uses
the real create/commit/link flow against the local test backend and stubs
only `ServerFeaturesQuery` and the `LinkArtifact` mutation.
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


def test_link_defers_all_membership_aliases(user, wandb_backend_spy: WandbBackendSpy):
    gql = wandb_backend_spy.gql

    # `feature_enabled()` caches the server's feature map for the sidecar's
    # lifetime, keyed by whichever call triggers the first load -- stub
    # before anything can trigger that, not right before `.link()`.
    _stub_server_features(
        wandb_backend_spy,
        pagination_enabled=True,
        ARTIFACT_MEMBERSHIP_IN_LINK_ARTIFACT_RESPONSE=True,
    )

    with wandb.init() as run:
        artifact = wandb.Artifact("my-link-pagination-artifact", type="dataset")
        with artifact.new_file("x.txt", "w") as f:
            f.write("hello")
        run.log_artifact(artifact)
        artifact.wait()

    entity, project = artifact.entity, artifact.project
    source_name = artifact.name
    target_project = "target-project"
    target_collection = "target-collection"

    membership = _membership_dict(
        membership_id="membership-id",
        entity=entity,
        project=target_project,
        collection=target_collection,
        version_index=3,
        artifact=_artifact_fragment_dict(
            artifact_id=artifact.id,
            entity=entity,
            project=project,
            collection=source_name.split(":")[0],
        ),
    )
    link_response = gql.Constant(
        content={
            "data": {
                "result": {"versionIndex": 3, "artifactMembership": membership},
            },
        }
    )
    wandb_backend_spy.stub_gql(gql.Matcher(operation="LinkArtifact"), link_response)

    first_alias_page = gql.Constant(
        content={
            "data": {
                "project": {
                    "artifactCollectionMembership": {
                        "aliasesConnection": _aliases_connection(
                            ["first-page"], has_next_page=True
                        )
                    }
                }
            },
        }
    )
    second_alias_page = gql.Constant(
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
    aliases_response = gql.Sequence([first_alias_page, second_alias_page])
    wandb_backend_spy.stub_gql(
        gql.Matcher(operation="ArtifactMembershipAliases"), aliases_response
    )

    linked = artifact.link(f"{entity}/{target_project}/{target_collection}")

    # Linking only cost one request against `LinkArtifact`; no alias page
    # is fetched until the returned artifact's aliases are read.
    assert link_response.total_calls == 1
    assert aliases_response.total_calls == 0
    assert "aliases @include(if: true)" not in link_response.requests[0].query
    assert "$includeAliases" not in link_response.requests[0].query
    assert linked.name == "target-collection:v3"
    assert linked.version == "v3"
    assert linked.is_link is True
    assert linked.source_name == source_name

    assert set(linked.aliases) == {"first-page", "second-page"}
    assert aliases_response.total_calls == 2
    for request in aliases_response.requests:
        assert request.variables["entity"] == entity
        assert request.variables["project"] == target_project
        assert request.variables["name"] == "target-collection:v3"
    assert aliases_response.requests[1].variables["cursor"] == "cursor-1"

    # A second read doesn't re-fetch anything.
    assert set(linked.aliases) == {"first-page", "second-page"}
    assert aliases_response.total_calls == 2


@mark.parametrize(
    ("membership_enabled", "pagination_enabled"),
    [(True, False), (False, True)],
)
def test_link_query_feature_fallbacks(
    user,
    wandb_backend_spy: WandbBackendSpy,
    mocker,
    membership_enabled: bool,
    pagination_enabled: bool,
):
    gql = wandb_backend_spy.gql
    _stub_server_features(
        wandb_backend_spy,
        pagination_enabled=pagination_enabled,
        ARTIFACT_MEMBERSHIP_IN_LINK_ARTIFACT_RESPONSE=membership_enabled,
    )

    with wandb.init() as run:
        artifact = wandb.Artifact("my-link-query-fallback", type="dataset")
        with artifact.new_file("x.txt", "w") as f:
            f.write("hello")
        run.log_artifact(artifact)
        artifact.wait()

    entity, project = artifact.entity, artifact.project
    response = {"versionIndex": 3}
    if membership_enabled:
        response["artifactMembership"] = {
            **_membership_dict(
                membership_id="membership-id",
                entity=entity,
                project="target-project",
                collection="target-collection",
                version_index=3,
                artifact=_artifact_fragment_dict(
                    artifact_id=artifact.id,
                    entity=entity,
                    project=project,
                    collection=artifact.name.split(":")[0],
                ),
            ),
            "aliases": [{"id": "alias-best", "alias": "best"}],
        }
    link_response = gql.Constant(content={"data": {"result": response}})
    wandb_backend_spy.stub_gql(gql.Matcher(operation="LinkArtifact"), link_response)

    if not membership_enabled:
        fetched = mocker.patch("wandb.Api")

    linked = artifact.link(f"{entity}/target-project/target-collection")

    assert link_response.total_calls == 1
    query = link_response.requests[0].query
    if membership_enabled:
        assert "$includeAliases" in query
        assert "aliases @include(if: true)" in query
        assert link_response.requests[0].variables["includeAliases"] is False
        assert linked.aliases == ["best"]
    else:
        assert "artifactMembership" not in query
        assert "$includeAliases" not in query
        assert "includeAliases" not in link_response.requests[0].variables
        assert linked is fetched.return_value._artifact.return_value
