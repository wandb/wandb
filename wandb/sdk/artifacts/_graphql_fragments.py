from textwrap import dedent

from wandb_graphql.language.printer import print_ast

from wandb.apis.public.utils import gql_compat
from wandb.sdk.internal.internal_api import Api as InternalApi

ARTIFACTS_TYPES_FRAGMENT = """
fragment ArtifactTypesFragment on ArtifactTypeConnection {
    edges {
         node {
             id
             name
             description
             createdAt
         }
         cursor
    }
    pageInfo {
        endCursor
        hasNextPage
    }
}
"""

ARTIFACT_FILES_FRAGMENT = """fragment FilesFragment on FileConnection {
    edges {
        node {
            id
            name: displayName
            url
            sizeBytes
            storagePath
            mimetype
            updatedAt
            digest
            md5
            directUrl
        }
        cursor
    }
    pageInfo {
        endCursor
        hasNextPage
    }
}"""


def _gql_artifact_fragment(include_aliases: bool = True) -> str:
    """Return a GraphQL query fragment with all parseable Artifact attributes."""
    allowed_fields = set(InternalApi().server_artifact_introspection())

    supports_ttl = "ttlIsInherited" in allowed_fields
    supports_tags = "tags" in allowed_fields
    supports_history_step = "historyStep" in allowed_fields

    omit_fields = [
        "ttlDurationSeconds",
        "ttlIsInherited",
        "aliases",
        "tags",
        "historyStep",
    ]
    if supports_ttl:
        omit_fields.remove("ttlDurationSeconds")
        omit_fields.remove("ttlIsInherited")

    if supports_tags:
        omit_fields.remove("tags")
    if supports_history_step:
        omit_fields.remove("historyStep")

    if include_aliases:
        omit_fields.remove("aliases")

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
        }
    """
