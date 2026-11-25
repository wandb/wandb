from unittest.mock import Mock

from wandb.sdk.artifacts._alias_paginator import MembershipAliasesPaginator
from wandb.sdk.artifacts._generated import ArtifactMembershipAliases


def _page_response(aliases, *, has_next_page, end_cursor=None):
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
                            {"node": {"id": f"alias-{a}", "alias": a}} for a in aliases
                        ],
                    }
                }
            }
        }
    )


def test_membership_aliases_paginator_iterates_multiple_pages():
    service_api = Mock()
    page_1 = _page_response(["alias-1"], has_next_page=True, end_cursor="cursor-1")
    page_2 = _page_response(["alias-2"], has_next_page=False)
    service_api.execute_graphql.side_effect = [page_1, page_2]

    paginator = MembershipAliasesPaginator(
        service_api,
        entity="test-entity",
        project="test-project",
        name="test-collection:v0",
    )

    assert list(paginator) == ["alias-1", "alias-2"]
    assert service_api.execute_graphql.call_count == 2


def test_membership_aliases_paginator_resumes_from_start_cursor():
    """A `start` cursor fetches only the remaining pages, not page one again."""
    service_api = Mock()
    service_api.execute_graphql.return_value = _page_response(
        ["alias-2"], has_next_page=False
    )

    paginator = MembershipAliasesPaginator(
        service_api,
        entity="test-entity",
        project="test-project",
        name="test-collection:v0",
        start="cursor-1",
    )

    assert list(paginator) == ["alias-2"]
    service_api.execute_graphql.assert_called_once()
    _, kwargs = service_api.execute_graphql.call_args
    assert kwargs["variables"]["cursor"] == "cursor-1"


def test_membership_aliases_paginator_drops_null_nodes():
    """A null edge node (allowed by the schema) is dropped, not a hard failure."""
    service_api = Mock()
    response = ArtifactMembershipAliases.model_validate(
        {
            "project": {
                "artifactCollectionMembership": {
                    "aliasesConnection": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "edges": [
                            {"node": {"id": "alias-1", "alias": "alias-1"}},
                            {"node": None},
                            {"node": {"id": "alias-2", "alias": "alias-2"}},
                        ],
                    }
                }
            }
        }
    )
    service_api.execute_graphql.return_value = response

    paginator = MembershipAliasesPaginator(
        service_api,
        entity="test-entity",
        project="test-project",
        name="test-collection:v0",
    )

    assert list(paginator) == ["alias-1", "alias-2"]


def test_membership_aliases_paginator_continues_past_empty_page():
    service_api = Mock()
    service_api.execute_graphql.side_effect = [
        _page_response([], has_next_page=True, end_cursor="cursor-1"),
        _page_response(["alias-2"], has_next_page=False),
    ]

    paginator = MembershipAliasesPaginator(
        service_api,
        entity="test-entity",
        project="test-project",
        name="test-collection:v0",
    )

    assert list(paginator) == ["alias-2"]
    assert service_api.execute_graphql.call_count == 2
