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

ARTIFACT_FILES_FRAGMENT = """fragment ArtifactFilesFragment on Artifact {
    files(names: $fileNames, after: $fileCursor, first: $fileLimit) {
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
    }
}"""


def _gql_artifact_fragment() -> str:
    """Return a GraphQL query fragment with all parseable Artifact attributes."""
    allowed_fields = set(InternalApi().server_artifact_introspection())

    supports_ttl = "ttlIsInherited" in allowed_fields
    supports_tags = "tags" in allowed_fields

    ttl_duration_seconds = "ttlDurationSeconds" if supports_ttl else ""
    ttl_is_inherited = "ttlIsInherited" if supports_ttl else ""

    tags = "tags {name}" if supports_tags else ""

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
            aliases {{
                artifactCollection {{
                    project {{
                        entityName
                        name
                    }}
                    name
                }}
                alias
            }}
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
