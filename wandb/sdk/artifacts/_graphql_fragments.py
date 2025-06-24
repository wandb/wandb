from __future__ import annotations

from textwrap import dedent

from wandb_graphql.language.printer import print_ast

from wandb.apis.public.utils import gql_compat
from wandb.sdk.internal.internal_api import Api as InternalApi

OMITTABLE_ARTIFACT_FIELDS = frozenset(
    {
        "ttlDurationSeconds",
        "ttlIsInherited",
        "aliases",
        "tags",
        "historyStep",
    }
)


def omit_artifact_fields(api: InternalApi) -> set[str]:
    """Return names of Artifact fields to remove from GraphQL requests (for server compatibility)."""
    allowed_fields = set(api.server_artifact_introspection())
    return set(OMITTABLE_ARTIFACT_FIELDS - allowed_fields)


def _gql_artifact_fragment(include_aliases: bool = True) -> str:
    """Return a GraphQL query fragment with all parseable Artifact attributes."""
    omit_fields = omit_artifact_fields(api=InternalApi())

    # Respect the `include_aliases` flag
    if not include_aliases:
        omit_fields.add("aliases")

    artifact_fragment_str = dedent(
        """\
        fragment ArtifactFragment on Artifact {
            id
            artifactSequence {
                project {
                    entityName
                    name
                }
                name
            }
            versionIndex
            artifactType {
                name
            }
            description
            metadata
            ttlDurationSeconds
            ttlIsInherited
            aliases {
                artifactCollection {
                    project {
                        entityName
                        name
                    }
                    name
                }
                alias
            }
            tags {
                name
            }
            historyStep
            state
            currentManifest {
                file {
                    directUrl
                }
            }
            commitHash
            fileCount
            createdAt
            updatedAt
        }"""
    )
    compat_doc = gql_compat(artifact_fragment_str, omit_fields=omit_fields)
    return print_ast(compat_doc)


def _gql_registry_fragment() -> str:
    return """
        fragment RegistryFragment on Project {
           id
            allowAllArtifactTypesInRegistry
            artifactTypes(includeAll: true) {
                edges {
                    node {
                        name
                    }
                }
            }
            name
            description
            createdAt
            updatedAt
            access
        }
    """
