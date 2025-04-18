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

    ttl_duration_seconds = "ttlDurationSeconds" if supports_ttl else ""
    ttl_is_inherited = "ttlIsInherited" if supports_ttl else ""

    tags = "tags {name}" if supports_tags else ""

    # The goal is to move all artifact aliases fetches to the membership level in the future
    # but this is a quick fix to unblock the registry work
    aliases = (
        """aliases {
                artifactCollection {
                    project {
                        entityName
                        name
                    }
                    name
                }
                alias
            }"""
        if include_aliases
        else ""
    )

    return f"""
        fragment ArtifactFragment on Artifact {{
            id
            artifactSequence {{
                project {{
                    entityName
                    name
                }}
                name
            }}
            versionIndex
            artifactType {{
                name
            }}
            description
            metadata
            {ttl_duration_seconds}
            {ttl_is_inherited}
            {aliases}
            {tags}
            state
            currentManifest {{
                file {{
                    directUrl
                }}
            }}
            commitHash
            fileCount
            createdAt
            updatedAt
        }}
    """


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
