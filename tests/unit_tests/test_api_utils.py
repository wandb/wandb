from __future__ import annotations

from textwrap import dedent

import pytest
from wandb.apis.public.utils import (
    fetch_org_from_settings_or_entity,
    gql_compat,
    parse_org_from_registry_path,
)
from wandb.sdk.internal.internal_api import _OrgNames
from wandb_gql import gql
from wandb_graphql import print_ast


@pytest.mark.parametrize(
    "path, path_type, expected",
    [
        # Valid cases
        ("my-org/wandb-registry-model", "project", "my-org"),
        ("my-org/wandb-registry-model/model:v1", "artifact", "my-org"),
        # Invalid cases
        ("", "project", ""),  # empty path
        ("", "artifact", ""),  # empty path
        ("my-org/myproject", "project", ""),  # not a Registry project
        ("my-org/myproject/model", "artifact", ""),  # not a Registry project
        # No orgs set in artifact paths
        ("model", "artifact", ""),
        ("wandb-registry-model/model", "artifact", ""),
        # No orgs set in project path
        ("wandb-registry-model", "project", ""),
    ],
)
def test_parse_org_from_registry_path(path, path_type, expected):
    """Test parse_org_from_registry_path with various input combinations."""
    result = parse_org_from_registry_path(path, path_type)
    assert result == expected


@pytest.fixture
def mock_fetch_orgs_and_org_entities_from_entity(monkeypatch):
    def mock_fetch_orgs(self, entity_name):
        responses = {
            "team-entity": [
                _OrgNames(entity_name="team-entity", display_name="team-org")
            ],
            "default-entity": [
                _OrgNames(entity_name="default-entity", display_name="default-org")
            ],
            "multi-org-user-entity": [
                _OrgNames(entity_name="org1", display_name="Org 1"),
                _OrgNames(entity_name="org2", display_name="Org 2"),
            ],
        }
        return responses.get(entity_name, [])

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api._fetch_orgs_and_org_entities_from_entity",
        mock_fetch_orgs,
    )


def test_fetch_org_from_settings_direct(mock_fetch_orgs_and_org_entities_from_entity):
    """Test when organization is directly specified in settings"""
    settings = {"organization": "org-display", "entity": "default-entity"}
    result = fetch_org_from_settings_or_entity(settings)
    assert result == "org-display"


def test_fetch_org_from_entity(mock_fetch_orgs_and_org_entities_from_entity):
    """Test fetching org when only entity is available"""
    settings = {"organization": None, "entity": "team-entity"}
    result = fetch_org_from_settings_or_entity(settings)
    assert result == "team-org"


def test_fetch_org_from_default_entity(mock_fetch_orgs_and_org_entities_from_entity):
    """Test fetching org using default entity when settings entity is None"""
    settings = {"organization": None, "entity": None}
    result = fetch_org_from_settings_or_entity(
        settings, default_entity="default-entity"
    )
    assert result == "default-org"


def test_no_entity_raises_error(mock_fetch_orgs_and_org_entities_from_entity):
    """Test that error is raised when no entity is available"""
    settings = {"organization": None, "entity": None}
    with pytest.raises(ValueError, match="No entity specified"):
        fetch_org_from_settings_or_entity(settings)


def test_no_orgs_found_raises_error(mock_fetch_orgs_and_org_entities_from_entity):
    """Test that error is raised when no orgs are found for entity"""
    settings = {"organization": None, "entity": "random-entity-possibly-not-real"}
    with pytest.raises(ValueError, match="No organizations found for entity"):
        fetch_org_from_settings_or_entity(settings)


def test_multiple_orgs_raises_error(mock_fetch_orgs_and_org_entities_from_entity):
    """Test that error is raised when multiple orgs are found for entity"""
    settings = {"organization": None, "entity": "multi-org-user-entity"}
    with pytest.raises(ValueError, match="Multiple organizations found for entity"):
        fetch_org_from_settings_or_entity(settings)


def normalize_gql_str(gql_str: str) -> str:
    """Test helper to normalize a GraphQL string for consistent comparison and easier diffing."""
    normalized_str = print_ast(gql(gql_str))
    # handle whitespace consistently for easier diffing
    return "\n".join(filter(str.strip, normalized_str.splitlines()))


def test_gql_compat():
    """Test that gql_compat rewrites a reasonably complex, realistic GraphQL request by omitting the expected parts."""
    omit_fragments = ["ArtifactInfo"]
    omit_variables = ["ttlDurationSeconds", "tagsToAdd", "tagsToDelete"]
    omit_fields = ["ttlDurationSeconds", "ttlIsInherited", "tags"]

    # GraphQL query with fragments on different types
    orig_query_str = dedent(
        """\
        mutation updateArtifact(
            $artifactID: ID!
            $description: String
            $metadata: JSONString
            $ttlDurationSeconds: Int64
            $tagsToAdd: [TagInput!]
            $tagsToDelete: [TagInput!]
            $aliases: [ArtifactAliasInput!]
        ) {
            updateArtifact(
                input: {
                    artifactID: $artifactID,
                    description: $description,
                    metadata: $metadata,
                    ttlDurationSeconds: $ttlDurationSeconds,
                    tagsToAdd: $tagsToAdd,
                    tagsToDelete: $tagsToDelete,
                    aliases: $aliases
                }
            ) {
                artifact {
                    ...ArtifactIdAndName
                    ... ArtifactInfo
                    ttlDurationSeconds
                    ttlIsInherited
                    tags {name}
                }
            }
        }
        fragment ArtifactIdAndName on Artifact {
            id
            name
        }
        fragment ArtifactInfo on Artifact {
            description
            versionIndex
        }
        """
    )
    expected_query_str = dedent(
        """\
        mutation updateArtifact(
            $artifactID: ID!
            $description: String
            $metadata: JSONString
            $aliases: [ArtifactAliasInput!]
        ) {
            updateArtifact(
                input: {
                    artifactID: $artifactID,
                    description: $description,
                    metadata: $metadata,
                    aliases: $aliases
                }
            ) {
                artifact {
                    ...ArtifactIdAndName
                }
            }
        }
        fragment ArtifactIdAndName on Artifact {
            id
            name
        }
        """
    )

    # Omit the Artifact type fragments
    compat_query = gql_compat(
        orig_query_str,
        omit_fragments=omit_fragments,
        omit_variables=omit_variables,
        omit_fields=omit_fields,
    )

    # Normalize the expected and actual query strings for consistent comparison
    orig_query_str = normalize_gql_str(orig_query_str)
    expected_query_str = normalize_gql_str(expected_query_str)
    compat_query_str = normalize_gql_str(print_ast(compat_query))

    assert compat_query_str == expected_query_str
    assert compat_query_str != orig_query_str


def test_gql_compat_omits_unused_fragments():
    # NOTE: fragment definitions below are deliberately in an unconventional order.
    # This is to test that the rewriter is agnostic to -- and preserves -- the original ordering.
    orig_query_str = dedent(
        """\
        fragment KeptFragmentA on KeptTypeA {
            keptInnerFieldA
        }

        query MyQuery {
            ...KeptFragmentA
            ...KeptFragmentB
            keptField
            removedParentField {...RemovedFragment}
        }

        fragment RemovedFragment on RemovedType {
            removedInnerField
            ...OrphanedFragment
        }
        fragment OrphanedFragment on RemovedType {
            anotherRemovedInnerField
        }

        fragment KeptFragmentB on KeptTypeB {
            ...KeptNestedFragment
        }
        fragment KeptNestedFragment on KeptTypeB {
            keptInnerFieldB
        }
        """
    )
    expected_query_str = dedent(
        """\
        fragment KeptFragmentA on KeptTypeA {
            keptInnerFieldA
        }
        query MyQuery {
            ...KeptFragmentA
            ...KeptFragmentB
            keptField
        }
        fragment KeptFragmentB on KeptTypeB {
            ...KeptNestedFragment
        }
        fragment KeptNestedFragment on KeptTypeB {
            keptInnerFieldB
        }
        """
    )

    # Omit RemovedFragment by its fragment (spread) name
    compat_query = gql_compat(orig_query_str, omit_fragments={"RemovedFragment"})

    compat_query_str = normalize_gql_str(print_ast(compat_query))
    expected_query_str = normalize_gql_str(expected_query_str)

    assert compat_query_str != orig_query_str
    assert compat_query_str == expected_query_str

    # Omit RemovedFragment by its _parent_ field name
    compat_query = gql_compat(orig_query_str, omit_fields={"removedParentField"})

    compat_query_str = normalize_gql_str(print_ast(compat_query))
    expected_query_str = normalize_gql_str(expected_query_str)

    assert compat_query_str != orig_query_str
    assert compat_query_str == expected_query_str


def test_gql_compat_rename_fields():
    orig_query_str = dedent(
        """\
        query ProjectArtifactCollections(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!
            $cursor: String,
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    artifactCollections: artifactCollections(after: $cursor) {
                        pageInfo {
                            endCursor
                            hasNextPage
                        }
                        totalCount
                    }
                }
            }
        }
        """
    )
    expected_query_str = dedent(
        """\
        query ProjectArtifactCollections(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!
            $cursor: String,
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    artifactCollections: artifactSequences(after: $cursor) {
                        pageInfo {
                            endCursor
                            hasNextPage
                        }
                        totalCount
                    }
                }
            }
        }
        """
    )
    compat_query = gql_compat(
        orig_query_str,
        rename_fields={"artifactCollections": "artifactSequences"},
    )

    # Normalize the query strings for consistent comparison
    orig_query_str = normalize_gql_str(orig_query_str)
    expected_query_str = normalize_gql_str(expected_query_str)
    compat_query_str = normalize_gql_str(print_ast(compat_query))

    assert compat_query_str == expected_query_str
    assert compat_query_str != orig_query_str
