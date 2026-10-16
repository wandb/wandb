from unittest.mock import Mock

from wandb.sdk.artifacts._alias_paginator import (
    MembershipAliasesPaginator,
    collect_membership_aliases,
)
from wandb.sdk.artifacts._generated import ArtifactMembershipAliases
from wandb.sdk.artifacts._generated.artifact_membership_by_name import (
    ArtifactMembershipByNameProjectArtifactCollectionMembershipAliasesConnection as MembershipAliasesConnection,
)


def _connection(aliases: list[str], *, has_next_page: bool, end_cursor: str | None):
    return MembershipAliasesConnection.model_validate(
        {
            "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
            "edges": [{"node": {"id": "PLACEHOLDER", "alias": a}} for a in aliases],
        }
    )


def test_collect_membership_aliases_single_page():
    service_api = Mock()
    first_page = _connection(["v0", "best"], has_next_page=False, end_cursor=None)

    aliases = collect_membership_aliases(
        first_page,
        service_api,
        entity="test-entity",
        project="test-project",
        name="test-collection:v0",
    )

    assert aliases == ["v0", "best"]
    service_api.execute_graphql.assert_not_called()


def test_collect_membership_aliases_multiple_pages():
    service_api = Mock()
    first_page = _connection(
        ["v0", "alias-1"], has_next_page=True, end_cursor="cursor-1"
    )

    second_page_response = ArtifactMembershipAliases.model_validate(
        {
            "project": {
                "artifactCollectionMembership": {
                    "aliasesConnection": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "edges": [{"node": {"id": "PLACEHOLDER", "alias": "alias-2"}}],
                    }
                }
            }
        }
    )
    service_api.execute_graphql.return_value = second_page_response

    aliases = collect_membership_aliases(
        first_page,
        service_api,
        entity="test-entity",
        project="test-project",
        name="test-collection:v0",
        per_page=2,
    )

    assert aliases == ["v0", "alias-1", "alias-2"]
    service_api.execute_graphql.assert_called_once()
    _, kwargs = service_api.execute_graphql.call_args
    assert kwargs["variables"]["cursor"] == "cursor-1"
    assert kwargs["variables"]["perPage"] == 2
    assert kwargs["variables"]["entity"] == "test-entity"
    assert kwargs["variables"]["project"] == "test-project"
    assert kwargs["variables"]["name"] == "test-collection:v0"


def test_membership_aliases_paginator_iterates_multiple_pages():
    service_api = Mock()
    page_1 = ArtifactMembershipAliases.model_validate(
        {
            "project": {
                "artifactCollectionMembership": {
                    "aliasesConnection": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                        "edges": [{"node": {"id": "PLACEHOLDER", "alias": "alias-1"}}],
                    }
                }
            }
        }
    )
    page_2 = ArtifactMembershipAliases.model_validate(
        {
            "project": {
                "artifactCollectionMembership": {
                    "aliasesConnection": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "edges": [{"node": {"id": "PLACEHOLDER", "alias": "alias-2"}}],
                    }
                }
            }
        }
    )
    service_api.execute_graphql.side_effect = [page_1, page_2]

    paginator = MembershipAliasesPaginator(
        service_api,
        entity="test-entity",
        project="test-project",
        name="test-collection:v0",
        start="cursor-0",
    )

    assert list(paginator) == ["alias-1", "alias-2"]
    assert service_api.execute_graphql.call_count == 2
