from unittest.mock import Mock

from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.artifacts._generated import (
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
        "artifactCollection": None,
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


def test_from_name_feature_enabled_paginates_remaining_aliases(mocker):
    service_api = Mock()
    service_api.feature_enabled.side_effect = _feature_enabled(True)

    first_response = _membership_by_name_response(
        aliases_connection={
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
            "edges": [{"node": {"id": "PLACEHOLDER", "alias": "v0"}}],
        },
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
    from_membership = mocker.patch.object(Artifact, "_from_membership")

    Artifact._from_name(path=_PATH, service_api=service_api)

    assert service_api.execute_graphql.call_count == 2
    first_call_kwargs = service_api.execute_graphql.call_args_list[0].kwargs
    assert "aliases" in first_call_kwargs["omit_fields"]

    _, from_membership_kwargs = from_membership.call_args
    assert from_membership_kwargs["membership_aliases"] == ["v0", "best"]
