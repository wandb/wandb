from unittest.mock import Mock

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._generated import (
    FETCH_LINKED_ARTIFACTS_GQL,
    UPDATE_ARTIFACT_GQL,
    ArtifactFragment,
    ArtifactMembershipAliases,
    ArtifactMembershipByName,
    FetchLinkedArtifacts,
)
from wandb.sdk.artifacts._validators import FullArtifactPath
from wandb.sdk.artifacts.artifact import Artifact

_PATH = FullArtifactPath(
    prefix="test-entity", project="test-project", name="test-collection:latest"
)


def _membership_data(
    *,
    flat_aliases=None,
    version_index=3,
    canonical_entity="canonical-entity",
    canonical_project="canonical-project",
):
    artifact = ArtifactFragment(
        name="test-collection",
        version_index=version_index,
        artifact_type={"name": "dataset"},
        artifact_sequence={
            "name": "test-collection",
            "project": {
                "id": "UHJvamVjdDox",
                "internalId": "UHJvamVjdEludGVybmFsSWQ6MQ==",
                "name": "source-project",
                "entity": {"name": "source-entity"},
            },
        },
        id="PLACEHOLDER",
        description=None,
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
    ).model_dump()
    membership = {
        "id": "PLACEHOLDER",
        "versionIndex": version_index,
        "createdAt": "PLACEHOLDER",
        "artifactCollection": {
            "__typename": "ArtifactPortfolio",
            "name": "test-collection",
            "project": {
                "id": "UHJvamVjdDox",
                "internalId": "UHJvamVjdEludGVybmFsSWQ6MQ==",
                "name": canonical_project,
                "entity": {"name": canonical_entity},
            },
        },
        "artifact": artifact,
    }
    if flat_aliases is not None:
        membership["aliases"] = [
            {"id": "PLACEHOLDER", "alias": alias} for alias in flat_aliases
        ]
    return ArtifactMembershipByName.model_validate(
        {"project": {"artifactCollectionMembership": membership}}
    )


def _alias_page(aliases, *, has_next_page=False, end_cursor=None):
    return ArtifactMembershipAliases.model_validate(
        {
            "project": {
                "artifactCollectionMembership": {
                    "aliasesConnection": {
                        "pageInfo": {
                            "hasNextPage": has_next_page,
                            "endCursor": end_cursor,
                        },
                        "edges": [
                            {"node": {"id": "PLACEHOLDER", "alias": alias}}
                            for alias in aliases
                        ],
                    }
                }
            }
        }
    )


def _linked_artifacts_response():
    return FetchLinkedArtifacts.model_validate(
        {
            "artifact": {
                "artifactMemberships": {
                    "edges": [
                        {
                            "node": {
                                "versionIndex": 7,
                                "createdAt": "PLACEHOLDER",
                                "aliases": [
                                    {"id": "linked-alias", "alias": "linked-only"}
                                ],
                                "artifactCollection": {
                                    "__typename": "ArtifactPortfolio",
                                    "name": "linked-collection",
                                    "project": {
                                        "id": "UHJvamVjdDox",
                                        "internalId": "UHJvamVjdEludGVybmFsSWQ6MQ==",
                                        "name": "linked-project",
                                        "entity": {"name": "linked-entity"},
                                    },
                                },
                            }
                        }
                    ]
                }
            }
        }
    )


def _service_api(*responses, pagination_enabled=True):
    service_api = Mock()
    service_api.feature_enabled.side_effect = lambda feature, **_: (
        feature == pb.ARTIFACT_MEMBERSHIP_ALIASES_PAGINATION and pagination_enabled
    )
    pending = iter(responses)
    service_api.variable_snapshots = []

    def execute_graphql(*args, **kwargs):
        service_api.variable_snapshots.append(dict(kwargs.get("variables") or {}))
        result = next(pending)
        if isinstance(result, Exception):
            raise result
        return result

    service_api.execute_graphql.side_effect = execute_graphql
    return service_api


def test_from_name_uses_flat_aliases_on_old_server():
    service_api = _service_api(
        _membership_data(flat_aliases=["v3", "best"]), pagination_enabled=False
    )

    artifact = Artifact._from_name(path=_PATH, service_api=service_api)

    assert artifact.aliases == ["best"]
    service_api.execute_graphql.assert_called_once()
    assert "aliases" not in service_api.execute_graphql.call_args.kwargs["omit_fields"]


def test_from_name_defers_all_alias_pages_and_uses_canonical_identity():
    service_api = _service_api(
        _membership_data(),
        _alias_page(["v3", "first"], has_next_page=True, end_cursor="cursor-1"),
        _alias_page(["best"]),
    )

    artifact = Artifact._from_name(path=_PATH, service_api=service_api)

    assert service_api.execute_graphql.call_count == 1
    assert artifact._aliases is None
    assert artifact._saved_aliases is None
    assert "aliases" in service_api.execute_graphql.call_args.kwargs["omit_fields"]

    assert artifact.aliases == ["first", "best"]
    assert service_api.execute_graphql.call_count == 3
    first_alias_vars = service_api.variable_snapshots[1]
    assert first_alias_vars["name"] == "test-collection:v3"
    assert first_alias_vars["entity"] == "canonical-entity"
    assert first_alias_vars["project"] == "canonical-project"
    assert first_alias_vars["cursor"] is None
    assert first_alias_vars["perPage"] == 1_000
    assert artifact._saved_aliases == ["first", "best"]
    assert artifact.aliases == ["first", "best"]
    assert service_api.execute_graphql.call_count == 3


def test_aliases_retry_starts_over_after_failed_later_page():
    service_api = _service_api(
        _membership_data(),
        _alias_page(["first"], has_next_page=True, end_cursor="cursor-1"),
        TimeoutError("transient network error"),
        _alias_page(["first"], has_next_page=True, end_cursor="cursor-1"),
        _alias_page(["best"]),
    )
    artifact = Artifact._from_name(path=_PATH, service_api=service_api)

    with pytest.raises(TimeoutError):
        _ = artifact.aliases

    assert artifact._aliases is None
    assert artifact.aliases == ["first", "best"]
    assert service_api.variable_snapshots[3]["cursor"] is None


def test_linked_artifacts_uses_own_aliases_not_source_later_pages(mocker):
    service_api = _service_api(
        _membership_data(
            canonical_entity="source-entity", canonical_project="source-project"
        ),
        _linked_artifacts_response(),
        _alias_page(["source-first"], has_next_page=True, end_cursor="cursor-1"),
        _alias_page(["source-later"]),
        Mock(result=Mock(artifact=Mock(), artifact_membership=None)),
    )
    source = Artifact._from_name(path=_PATH, service_api=service_api)
    assert source._aliases is None

    linked = source.linked_artifacts[0]

    assert service_api.execute_graphql.call_args_list[1].args[0] == (
        FETCH_LINKED_ARTIFACTS_GQL
    )
    assert linked.is_link is True
    assert linked.aliases == ["linked-only", "v7"]
    assert service_api.execute_graphql.call_count == 2
    assert source.aliases == ["source-first", "source-later"]
    assert linked.aliases == ["linked-only", "v7"]
    assert service_api.execute_graphql.call_count == 4

    # Saving an edit to the linked artifact must never try to delete a
    # source alias from the source's later page.
    linked.aliases = ["v7", "replacement"]
    mocker.patch.object(linked, "_is_source_project_read_only", return_value=False)
    add_aliases = mocker.patch.object(linked, "_add_aliases")
    delete_aliases = mocker.patch.object(linked, "_delete_aliases")
    mocker.patch.object(linked, "_assign_attrs")
    linked.save()

    assert add_aliases.call_args.args[0] == {"replacement"}
    assert delete_aliases.call_args.args[0] == {"linked-only"}
    assert service_api.execute_graphql.call_count == 5
    assert service_api.execute_graphql.call_args.args[0] == UPDATE_ARTIFACT_GQL


def test_update_skips_alias_fetch_when_aliases_untouched(mocker):
    # Canonical entity/project match the source: a non-link artifact, so
    # `_update()` goes straight to `UpdateArtifact` instead of first calling
    # `_is_source_project_read_only()` -- which would otherwise consume the
    # mocked `UpdateArtifact` response as an `IsProjectReadOnly` response
    # (truthy either way) and skip the mutation without anyone noticing.
    service_api = _service_api(
        _membership_data(
            canonical_entity="source-entity", canonical_project="source-project"
        ),
        Mock(result=Mock(artifact=Mock(), artifact_membership=None)),
    )
    artifact = Artifact._from_name(path=_PATH, service_api=service_api)
    assert artifact.is_link is False
    add_aliases = mocker.patch.object(artifact, "_add_aliases")
    delete_aliases = mocker.patch.object(artifact, "_delete_aliases")
    mocker.patch.object(artifact, "_assign_attrs")

    artifact.metadata = {"changed": True}
    artifact.save()

    assert service_api.execute_graphql.call_count == 2
    assert service_api.execute_graphql.call_args.args[0] == UPDATE_ARTIFACT_GQL
    add_aliases.assert_not_called()
    delete_aliases.assert_not_called()
    assert artifact._aliases is None


def test_update_diffs_explicit_alias_edit_against_fetched_aliases(mocker):
    # See the comment in the previous test: a non-link fixture, so the
    # mutation actually runs instead of being silently skipped.
    service_api = _service_api(
        _membership_data(
            canonical_entity="source-entity", canonical_project="source-project"
        ),
        _alias_page(
            ["v3", "keep", "remove-first"],
            has_next_page=True,
            end_cursor="cursor-1",
        ),
        _alias_page(["remove-later"]),
        Mock(result=Mock(artifact=Mock(), artifact_membership=None)),
    )
    artifact = Artifact._from_name(path=_PATH, service_api=service_api)
    assert artifact.is_link is False
    artifact.aliases = ["keep", "new"]
    add_aliases = mocker.patch.object(artifact, "_add_aliases")
    delete_aliases = mocker.patch.object(artifact, "_delete_aliases")
    mocker.patch.object(artifact, "_assign_attrs")

    artifact.save()

    expected_target = FullArtifactPath(
        prefix=artifact.entity, project=artifact.project, name="test-collection"
    )
    assert add_aliases.call_args.args[0] == {"new"}
    assert add_aliases.call_args.kwargs["target"] == expected_target
    assert delete_aliases.call_args.args[0] == {"remove-first", "remove-later"}
    assert delete_aliases.call_args.kwargs["target"] == expected_target
    assert service_api.execute_graphql.call_count == 4
    assert service_api.execute_graphql.call_args.args[0] == UPDATE_ARTIFACT_GQL
