"""Tests for lazy membership-aliases pagination in `Artifact.link()`.

Mirrors `test_artifact_from_name.py`'s approach: a paginated
`aliasesConnection` is requested instead of the unbounded flat `aliases`
field once `ARTIFACT_MEMBERSHIP_ALIASES_PAGINATION` is enabled, and only the
first page is fetched eagerly -- remaining pages are deferred until
something actually reads `.aliases`.
"""

from __future__ import annotations

from unittest.mock import Mock

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._generated import (
    ArtifactFragment,
    ArtifactMembershipAliases,
    LinkArtifact,
)
from wandb.sdk.artifacts._validators import FullArtifactPath
from wandb.sdk.artifacts.artifact import Artifact


def _feature_enabled(enabled_features):
    """A `feature_enabled` side effect; defaults to False for every feature."""

    def _enabled(feature, **_):
        return bool(enabled_features.get(feature, False))

    return _enabled


def _artifact_fragment(*, entity="test-entity", project="test-project"):
    return ArtifactFragment(
        name="test-collection",
        version_index=0,
        artifact_type={"name": "dataset"},
        artifact_sequence={
            "name": "test-collection",
            "project": {
                "id": "UHJvamVjdDox",
                "internalId": "UHJvamVjdEludGVybmFsSWQ6MQ==",
                "name": project,
                "entity": {"name": entity},
            },
        },
        id="artifact-id",
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
    )


def _artifact_fragment_dict(*, entity="test-entity", project="test-project"):
    return _artifact_fragment(entity=entity, project=project).model_dump()


def _logged_artifact(service_api, *, entity="test-entity", project="test-project"):
    """A committed (non-draft) Artifact, ready to `.link()`."""
    path = FullArtifactPath(prefix=entity, project=project, name="test-collection:v0")
    artifact = Artifact._from_attrs(
        path, _artifact_fragment(entity=entity, project=project), service_api
    )
    artifact._saved_aliases = list(artifact._aliases)
    artifact._saved_tags = list(artifact.tags)
    return artifact


def _membership_dict(
    *, entity="test-entity", project="test-project", version_index=3, aliases_connection
):
    return {
        "id": "membership-id",
        "versionIndex": version_index,
        "createdAt": "PLACEHOLDER",
        "artifactCollection": {
            "__typename": "ArtifactPortfolio",
            "name": "test-collection",
            "project": {
                "id": "UHJvamVjdDox",
                "internalId": "UHJvamVjdEludGVybmFsSWQ6MQ==",
                "name": project,
                "entity": {"name": entity},
            },
        },
        "artifact": _artifact_fragment_dict(entity=entity, project=project),
        "aliasesConnection": aliases_connection,
    }


def test_link_feature_disabled_uses_flat_aliases(mocker):
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(
        {pb.ARTIFACT_MEMBERSHIP_IN_LINK_ARTIFACT_RESPONSE: True}
    )
    artifact = _logged_artifact(service_api)

    membership = _membership_dict(aliases_connection=None)
    membership.pop("aliasesConnection")
    membership["aliases"] = [{"id": "alias-id", "alias": "best"}]
    service_api.execute_graphql.return_value = LinkArtifact.model_validate(
        {"result": {"versionIndex": 3, "artifactMembership": membership}}
    )
    from_membership = mocker.patch.object(Artifact, "_from_membership")

    artifact.link("test-entity/other-project/target-collection")

    _, kwargs = service_api.execute_graphql.call_args
    assert "perPage" in kwargs["omit_variables"]
    assert "aliasesConnection" in kwargs["omit_fields"]
    assert "aliases" not in kwargs["omit_fields"]

    _, from_membership_kwargs = from_membership.call_args
    assert from_membership_kwargs["membership_aliases"] is None
    assert from_membership_kwargs["aliases_paginator"] is None


def test_link_feature_enabled_single_page(mocker):
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(
        {
            pb.ARTIFACT_MEMBERSHIP_IN_LINK_ARTIFACT_RESPONSE: True,
            pb.ARTIFACT_MEMBERSHIP_ALIASES_PAGINATION: True,
        }
    )
    artifact = _logged_artifact(service_api)

    membership = _membership_dict(
        version_index=3,
        aliases_connection={
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "edges": [{"node": {"id": "alias-id", "alias": "best"}}],
        },
    )
    service_api.execute_graphql.return_value = LinkArtifact.model_validate(
        {"result": {"versionIndex": 3, "artifactMembership": membership}}
    )
    from_membership = mocker.patch.object(Artifact, "_from_membership")

    artifact.link("test-entity/other-project/target-collection")

    _, kwargs = service_api.execute_graphql.call_args
    assert "perPage" not in kwargs["omit_variables"]
    assert "aliasesConnection" not in kwargs["omit_fields"]
    assert "aliases" in kwargs["omit_fields"]

    service_api.execute_graphql.assert_called_once()
    _, from_membership_kwargs = from_membership.call_args
    assert from_membership_kwargs["membership_aliases"] == ["best"]
    assert from_membership_kwargs["aliases_paginator"] is None


def test_link_feature_enabled_defers_remaining_pages(mocker):
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(
        {
            pb.ARTIFACT_MEMBERSHIP_IN_LINK_ARTIFACT_RESPONSE: True,
            pb.ARTIFACT_MEMBERSHIP_ALIASES_PAGINATION: True,
        }
    )
    artifact = _logged_artifact(service_api)

    membership = _membership_dict(
        version_index=3,
        aliases_connection={
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
            "edges": [{"node": {"id": "alias-id", "alias": "best"}}],
        },
    )
    service_api.execute_graphql.return_value = LinkArtifact.model_validate(
        {"result": {"versionIndex": 3, "artifactMembership": membership}}
    )
    from_membership = mocker.patch.object(Artifact, "_from_membership")

    artifact.link("test-entity/other-project/target-collection")

    # Exactly one request: the continuation page is never fetched here.
    service_api.execute_graphql.assert_called_once()
    _, from_membership_kwargs = from_membership.call_args
    assert from_membership_kwargs["membership_aliases"] == ["best"]
    assert from_membership_kwargs["aliases_paginator"] is not None


def _second_page_response(alias="second-page"):
    return ArtifactMembershipAliases.model_validate(
        {
            "project": {
                "artifactCollectionMembership": {
                    "aliasesConnection": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "edges": [{"node": {"id": "alias-id", "alias": alias}}],
                    }
                }
            }
        }
    )


def test_link_aliases_property_lazily_fetches_remaining_pages():
    """Only reading `.aliases` on the linked artifact should fetch page 2."""
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(
        {
            pb.ARTIFACT_MEMBERSHIP_IN_LINK_ARTIFACT_RESPONSE: True,
            pb.ARTIFACT_MEMBERSHIP_ALIASES_PAGINATION: True,
        }
    )
    artifact = _logged_artifact(service_api)

    membership = _membership_dict(
        version_index=3,
        aliases_connection={
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
            "edges": [{"node": {"id": "alias-id", "alias": "first-page"}}],
        },
    )
    link_response = LinkArtifact.model_validate(
        {"result": {"versionIndex": 3, "artifactMembership": membership}}
    )
    service_api.execute_graphql.side_effect = [
        link_response,
        _second_page_response(),
    ]

    linked = artifact.link("test-entity/other-project/target-collection")

    # Linking only cost one request; the continuation page isn't fetched yet.
    service_api.execute_graphql.assert_called_once()

    aliases = linked.aliases

    assert service_api.execute_graphql.call_count == 2
    assert set(aliases) == {"first-page", "second-page"}

    # A second read doesn't re-fetch anything.
    assert linked.aliases == aliases
    assert service_api.execute_graphql.call_count == 2
