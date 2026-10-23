from unittest.mock import Mock

import pytest
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._generated import (
    ArtifactFragment,
    ArtifactMembershipAliases,
    ArtifactMembershipByName,
)
from wandb.sdk.artifacts._validators import FullArtifactPath
from wandb.sdk.artifacts.artifact import Artifact

_PATH = FullArtifactPath(
    prefix="test-entity", project="test-project", name="test-collection:v0"
)


def _membership_data(*, flat_aliases=None, aliases_connection=None):
    data = {
        "id": "PLACEHOLDER",
        "versionIndex": 1,
        "createdAt": "PLACEHOLDER",
        "artifactCollection": {
            "__typename": "ArtifactPortfolio",
            "name": "test-collection",
            "project": {
                "id": "UHJvamVjdDox",
                "internalId": "UHJvamVjdEludGVybmFsSWQ6MQ==",
                "name": "test-project",
                "entity": {"name": "test-entity"},
            },
        },
        "artifact": None,
    }
    # Omit the key entirely (rather than an empty list) when flat_aliases isn't
    # given, mirroring a real server response when `aliases` is stripped from
    # the request via `omit_fields`.
    if flat_aliases is not None:
        data["aliases"] = [{"id": "PLACEHOLDER", "alias": a} for a in flat_aliases]
    if aliases_connection is not None:
        data["aliasesConnection"] = aliases_connection
    return data


def _membership_by_name_response(**kwargs):
    return ArtifactMembershipByName.model_validate(
        {"project": {"artifactCollectionMembership": _membership_data(**kwargs)}}
    )


def _feature_enabled(enabled: bool):
    return lambda feature, **_: (
        feature == pb.ARTIFACT_MEMBERSHIP_ALIASES_PAGINATION and enabled
    )


def test_from_name_feature_disabled_uses_flat_aliases(mocker):
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(False)
    service_api.execute_graphql.return_value = _membership_by_name_response(
        flat_aliases=["v0", "best"]
    )
    from_membership = mocker.patch.object(Artifact, "_from_membership")

    Artifact._from_name(path=_PATH, service_api=service_api)

    _, kwargs = service_api.execute_graphql.call_args
    assert kwargs["omit_variables"] == {"perPage"}
    assert "aliasesConnection" in kwargs["omit_fields"]
    assert "aliases" not in kwargs["omit_fields"]

    _, from_membership_kwargs = from_membership.call_args
    assert from_membership_kwargs["membership_aliases"] is None
    assert from_membership_kwargs["aliases_paginator"] is None


def test_from_name_feature_enabled_single_page(mocker):
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(True)
    # No `flat_aliases`: a real server omits the unbounded `aliases` field
    # from the response entirely once we stop requesting it.
    service_api.execute_graphql.return_value = _membership_by_name_response(
        aliases_connection={
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "edges": [{"node": {"id": "PLACEHOLDER", "alias": "v0"}}],
        },
    )
    from_membership = mocker.patch.object(Artifact, "_from_membership")

    Artifact._from_name(path=_PATH, service_api=service_api)

    _, kwargs = service_api.execute_graphql.call_args
    assert kwargs["omit_variables"] == {"includeAliases"}
    assert "aliasesConnection" not in kwargs["omit_fields"]
    # The whole point of pagination: never request the unbounded flat field
    # once the paginated connection is available.
    assert "aliases" in kwargs["omit_fields"]

    service_api.execute_graphql.assert_called_once()
    _, from_membership_kwargs = from_membership.call_args
    assert from_membership_kwargs["membership_aliases"] == ["v0"]
    assert from_membership_kwargs["aliases_paginator"] is None


def test_from_name_feature_enabled_defers_remaining_pages(mocker):
    """`_from_name` should not fetch past the first page on its own.

    Remaining pages are only worth fetching if something actually reads
    `.aliases`; `_from_name` itself must not pay for that eagerly.
    """
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(True)

    first_response = _membership_by_name_response(
        aliases_connection={
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
            "edges": [{"node": {"id": "PLACEHOLDER", "alias": "v0"}}],
        },
    )
    service_api.execute_graphql.return_value = first_response
    from_membership = mocker.patch.object(Artifact, "_from_membership")

    Artifact._from_name(path=_PATH, service_api=service_api)

    # Exactly one request: the continuation page is never fetched here.
    service_api.execute_graphql.assert_called_once()
    _, from_membership_kwargs = from_membership.call_args
    assert from_membership_kwargs["membership_aliases"] == ["v0"]
    assert from_membership_kwargs["aliases_paginator"] is not None


def _full_membership_data(*, aliases_connection):
    """A membership payload with enough real data to skip `_from_membership`."""
    artifact_fragment = ArtifactFragment(
        name="test-collection",
        version_index=0,
        artifact_type={"name": "dataset"},
        artifact_sequence={
            "name": "test-collection",
            "project": {
                "id": "UHJvamVjdDox",
                "internalId": "UHJvamVjdEludGVybmFsSWQ6MQ==",
                "name": "test-project",
                "entity": {"name": "test-entity"},
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

    data = _membership_data(aliases_connection=aliases_connection)
    data["artifact"] = artifact_fragment
    data["artifactCollection"] = {
        "__typename": "ArtifactPortfolio",
        "name": "test-collection",
        "project": {
            "id": "UHJvamVjdDox",
            "internalId": "UHJvamVjdEludGVybmFsSWQ6MQ==",
            "name": "test-project",
            "entity": {"name": "test-entity"},
        },
    }
    return data


def test_aliases_property_lazily_fetches_remaining_pages():
    """Fetching the artifact shouldn't pay for pages nothing asked for.

    Only touching `.aliases` should trigger the continuation request; the
    fetch that constructs the `Artifact` must not do it on its own.
    """
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(True)

    first_response = ArtifactMembershipByName.model_validate(
        {
            "project": {
                "artifactCollectionMembership": _full_membership_data(
                    aliases_connection={
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                        "edges": [
                            {"node": {"id": "PLACEHOLDER", "alias": "first-page"}}
                        ],
                    }
                )
            }
        }
    )
    second_response = ArtifactMembershipAliases.model_validate(
        {
            "project": {
                "artifactCollectionMembership": {
                    "aliasesConnection": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "edges": [{"node": {"id": "PLACEHOLDER", "alias": "best"}}],
                    }
                }
            }
        }
    )
    service_api.execute_graphql.side_effect = [first_response, second_response]

    artifact = Artifact._from_name(path=_PATH, service_api=service_api)

    # Constructing the artifact only cost the first page.
    service_api.execute_graphql.assert_called_once()

    aliases = artifact.aliases

    # Reading `.aliases` is what triggers the continuation request.
    assert service_api.execute_graphql.call_count == 2
    assert set(aliases) == {"first-page", "best"}

    # A second read doesn't re-fetch anything.
    assert artifact.aliases == aliases
    assert service_api.execute_graphql.call_count == 2


def test_from_name_continuation_uses_membership_identity_not_request_path(mocker):
    """The continuation paginator must resume against the membership actually

    fetched, not the (possibly alias-based) name the caller requested.

    Regression test: an alias like `:latest` can move to point at a
    different version between this fetch and a later continuation fetch.
    Resuming with the original alias-based name and entity/project could
    silently apply this cursor to a different membership (e.g. the new
    target of a moved alias, or the pre-migration project for a
    migrated-registry redirect).
    """
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(True)

    # Deliberately an alias-based path, not a version -- this is exactly the
    # case where the lookup name can later point somewhere else.
    path = FullArtifactPath(
        prefix="test-entity", project="test-project", name="test-collection:latest"
    )
    data = _membership_data(
        aliases_connection={
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
            "edges": [{"node": {"id": "PLACEHOLDER", "alias": "v3"}}],
        },
    )
    data["versionIndex"] = 3
    # The membership's own canonical project/entity differ from the request
    # path, e.g. a migrated-registry redirect -- the continuation must use
    # these, not the request path's.
    data["artifactCollection"]["project"]["name"] = "canonical-project"
    data["artifactCollection"]["project"]["entity"]["name"] = "canonical-entity"
    service_api.execute_graphql.return_value = ArtifactMembershipByName.model_validate(
        {"project": {"artifactCollectionMembership": data}}
    )
    from_membership = mocker.patch.object(Artifact, "_from_membership")

    Artifact._from_name(path=path, service_api=service_api)

    _, from_membership_kwargs = from_membership.call_args
    paginator = from_membership_kwargs["aliases_paginator"]
    assert paginator is not None
    assert paginator.variables["name"] == "test-collection:v3"
    assert paginator.variables["entity"] == "canonical-entity"
    assert paginator.variables["project"] == "canonical-project"


def test_aliases_property_retries_after_failed_continuation_fetch():
    """A transient error fetching a continuation page must not discard it.

    Regression test: clearing `_aliases_paginator` before iteration succeeds
    would permanently and silently drop access to not-yet-fetched aliases
    after any transient error -- a retried `.aliases` read would just return
    whatever was already loaded, with no way to try again.
    """
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(True)

    first_response = ArtifactMembershipByName.model_validate(
        {
            "project": {
                "artifactCollectionMembership": _full_membership_data(
                    aliases_connection={
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                        "edges": [
                            {"node": {"id": "PLACEHOLDER", "alias": "first-page"}}
                        ],
                    }
                )
            }
        }
    )
    second_response = ArtifactMembershipAliases.model_validate(
        {
            "project": {
                "artifactCollectionMembership": {
                    "aliasesConnection": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "edges": [{"node": {"id": "PLACEHOLDER", "alias": "best"}}],
                    }
                }
            }
        }
    )
    service_api.execute_graphql.side_effect = [
        first_response,
        TimeoutError("transient network error"),
        second_response,
    ]

    artifact = Artifact._from_name(path=_PATH, service_api=service_api)

    with pytest.raises(TimeoutError):
        artifact.aliases  # noqa: B018 (property access is the point)

    # The failed fetch must not have discarded the pending paginator.
    assert artifact._aliases_paginator is not None

    # Retrying succeeds and returns the complete set.
    assert set(artifact.aliases) == {"first-page", "best"}
    assert artifact._aliases_paginator is None
