"""Public API: artifacts."""
import json
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence

from wandb_gql import Client, gql

import wandb
from wandb.apis import public
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import Paginator

if TYPE_CHECKING:
    from wandb.apis.public import RetryingClient, Run


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

# TODO, factor out common file fragment
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
            }
            cursor
        }
        pageInfo {
            endCursor
            hasNextPage
        }
    }
}"""


class ArtifactTypes(Paginator):
    QUERY = gql(
        """
        query ProjectArtifacts(
            $entityName: String!,
            $projectName: String!,
            $cursor: String,
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactTypes(after: $cursor) {
                    ...ArtifactTypesFragment
                }
            }
        }
        %s
    """
        % ARTIFACTS_TYPES_FRAGMENT
    )

    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        per_page: Optional[int] = 50,
    ):
        self.entity = entity
        self.project = project

        variable_values = {
            "entityName": entity,
            "projectName": project,
        }

        super().__init__(client, variable_values, per_page)

    @property
    def length(self):
        # TODO
        return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["artifactTypes"]["pageInfo"][
                "hasNextPage"
            ]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["artifactTypes"]["edges"][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update({"cursor": self.cursor})

    def convert_objects(self):
        if self.last_response["project"] is None:
            return []
        return [
            ArtifactType(
                self.client, self.entity, self.project, r["node"]["name"], r["node"]
            )
            for r in self.last_response["project"]["artifactTypes"]["edges"]
        ]


class ArtifactType:
    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        type_name: str,
        attrs: Optional[Mapping[str, Any]] = None,
    ):
        self.client = client
        self.entity = entity
        self.project = project
        self.type = type_name
        self._attrs = attrs
        if self._attrs is None:
            self.load()

    def load(self):
        query = gql(
            """
        query ProjectArtifactType(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    id
                    name
                    description
                    createdAt
                }
            }
        }
        """
        )
        response: Optional[Mapping[str, Any]] = self.client.execute(
            query,
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactTypeName": self.type,
            },
        )
        if (
            response is None
            or response.get("project") is None
            or response["project"].get("artifactType") is None
        ):
            raise ValueError("Could not find artifact type %s" % self.type)
        self._attrs = response["project"]["artifactType"]
        return self._attrs

    @property
    def id(self):
        return self._attrs["id"]

    @property
    def name(self):
        return self._attrs["name"]

    @normalize_exceptions
    def collections(self, per_page=50):
        """Artifact collections."""
        return ArtifactCollections(self.client, self.entity, self.project, self.type)

    def collection(self, name):
        return ArtifactCollection(
            self.client, self.entity, self.project, name, self.type
        )

    def __repr__(self):
        return f"<ArtifactType {self.type}>"


class ArtifactCollections(Paginator):
    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        type_name: str,
        per_page: Optional[int] = 50,
    ):
        self.entity = entity
        self.project = project
        self.type_name = type_name

        variable_values = {
            "entityName": entity,
            "projectName": project,
            "artifactTypeName": type_name,
        }

        self.QUERY = gql(
            """
            query ProjectArtifactCollections(
                $entityName: String!,
                $projectName: String!,
                $artifactTypeName: String!
                $cursor: String,
            ) {
                project(name: $projectName, entityName: $entityName) {
                    artifactType(name: $artifactTypeName) {
                        artifactCollections: %s(after: $cursor) {
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                            totalCount
                            edges {
                                node {
                                    id
                                    name
                                    description
                                    createdAt
                                }
                                cursor
                            }
                        }
                    }
                }
            }
        """
            % artifact_collection_plural_edge_name(
                server_supports_artifact_collections_gql_edges(client)
            )
        )

        super().__init__(client, variable_values, per_page)

    @property
    def length(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollections"][
                "totalCount"
            ]
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollections"][
                "pageInfo"
            ]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollections"][
                "edges"
            ][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update({"cursor": self.cursor})

    def convert_objects(self):
        return [
            ArtifactCollection(
                self.client,
                self.entity,
                self.project,
                r["node"]["name"],
                self.type_name,
            )
            for r in self.last_response["project"]["artifactType"][
                "artifactCollections"
            ]["edges"]
        ]


class ArtifactCollection:
    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        name: str,
        type: str,
        attrs: Optional[Mapping[str, Any]] = None,
    ):
        self.client = client
        self.entity = entity
        self.project = project
        self.name = name
        self.type = type
        self._attrs = attrs
        if self._attrs is None:
            self.load()
        self._aliases = [a["node"]["alias"] for a in self._attrs["aliases"]["edges"]]

    @property
    def id(self):
        return self._attrs["id"]

    @normalize_exceptions
    def artifacts(self, per_page=50):
        """Artifacts."""
        return Artifacts(
            self.client,
            self.entity,
            self.project,
            self.name,
            self.type,
            per_page=per_page,
        )

    @property
    def aliases(self):
        """Artifact Collection Aliases."""
        return self._aliases

    def load(self):
        query = gql(
            """
        query ArtifactCollection(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!,
            $artifactCollectionName: String!,
            $cursor: String,
            $perPage: Int = 1000
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    artifactCollection: %s(name: $artifactCollectionName) {
                        id
                        name
                        description
                        createdAt
                        aliases(after: $cursor, first: $perPage){
                            edges {
                                node {
                                    alias
                                }
                                cursor
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
        """
            % artifact_collection_edge_name(
                server_supports_artifact_collections_gql_edges(self.client)
            )
        )
        response = self.client.execute(
            query,
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactTypeName": self.type,
                "artifactCollectionName": self.name,
            },
        )
        if (
            response is None
            or response.get("project") is None
            or response["project"].get("artifactType") is None
            or response["project"]["artifactType"].get("artifactCollection") is None
        ):
            raise ValueError("Could not find artifact type %s" % self.type)
        self._attrs = response["project"]["artifactType"]["artifactCollection"]
        return self._attrs

    @normalize_exceptions
    def is_sequence(self) -> bool:
        """Return True if this is a sequence."""
        query = gql(
            """
            query FindSequence($entity: String!, $project: String!, $collection: String!, $type: String!) {
                project(name: $project, entityName: $entity) {
                    artifactType(name: $type) {
                        __typename
                        artifactSequence(name: $collection) {
                            __typename
                        }
                    }
                }
            }
            """
        )
        variables = {
            "entity": self.entity,
            "project": self.project,
            "collection": self.name,
            "type": self.type,
        }
        res = self.client.execute(query, variable_values=variables)
        sequence = res["project"]["artifactType"]["artifactSequence"]
        return sequence is not None and sequence["__typename"] == "ArtifactSequence"

    @normalize_exceptions
    def delete(self):
        """Delete the entire artifact collection."""
        if self.is_sequence():
            mutation = gql(
                """
                mutation deleteArtifactSequence($id: ID!) {
                    deleteArtifactSequence(input: {
                        artifactSequenceID: $id
                    }) {
                        artifactCollection {
                            state
                        }
                    }
                }
                """
            )
        else:
            mutation = gql(
                """
                mutation deleteArtifactPortfolio($id: ID!) {
                    deleteArtifactPortfolio(input: {
                        artifactPortfolioID: $id
                    }) {
                        artifactCollection {
                            state
                        }
                    }
                }
                """
            )
        self.client.execute(mutation, variable_values={"id": self.id})

    def __repr__(self):
        return f"<ArtifactCollection {self.name} ({self.type})>"


class Artifacts(Paginator):
    """An iterable collection of artifact versions associated with a project and optional filter.

    This is generally used indirectly via the `Api`.artifact_versions method.
    """

    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        collection_name: str,
        type: str,
        filters: Optional[Mapping[str, Any]] = None,
        order: Optional[str] = None,
        per_page: int = 50,
    ):
        self.entity = entity
        self.collection_name = collection_name
        self.type = type
        self.project = project
        self.filters = {"state": "COMMITTED"} if filters is None else filters
        self.order = order
        variables = {
            "project": self.project,
            "entity": self.entity,
            "order": self.order,
            "type": self.type,
            "collection": self.collection_name,
            "filters": json.dumps(self.filters),
        }
        self.QUERY = gql(
            """
            query Artifacts($project: String!, $entity: String!, $type: String!, $collection: String!, $cursor: String, $perPage: Int = 50, $order: String, $filters: JSONString) {{
                project(name: $project, entityName: $entity) {{
                    artifactType(name: $type) {{
                        artifactCollection: {}(name: $collection) {{
                            name
                            artifacts(filters: $filters, after: $cursor, first: $perPage, order: $order) {{
                                totalCount
                                edges {{
                                    node {{
                                        ...ArtifactFragment
                                    }}
                                    version
                                    cursor
                                }}
                                pageInfo {{
                                    endCursor
                                    hasNextPage
                                }}
                            }}
                        }}
                    }}
                }}
            }}
            {}
            """.format(
                artifact_collection_edge_name(
                    server_supports_artifact_collections_gql_edges(client)
                ),
                wandb.Artifact._get_gql_artifact_fragment(),
            )
        )
        super().__init__(client, variables, per_page)

    @property
    def length(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollection"][
                "artifacts"
            ]["totalCount"]
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollection"][
                "artifacts"
            ]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollection"][
                "artifacts"
            ]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self):
        if self.last_response["project"]["artifactType"]["artifactCollection"] is None:
            return []
        return [
            wandb.Artifact._from_attrs(
                self.entity,
                self.project,
                self.collection_name + ":" + a["version"],
                a["node"],
                self.client,
            )
            for a in self.last_response["project"]["artifactType"][
                "artifactCollection"
            ]["artifacts"]["edges"]
        ]


class RunArtifacts(Paginator):
    def __init__(
        self, client: Client, run: "Run", mode="logged", per_page: Optional[int] = 50
    ):
        output_query = gql(
            """
            query RunOutputArtifacts(
                $entity: String!, $project: String!, $runName: String!, $cursor: String, $perPage: Int,
            ) {
                project(name: $project, entityName: $entity) {
                    run(name: $runName) {
                        outputArtifacts(after: $cursor, first: $perPage) {
                            totalCount
                            edges {
                                node {
                                    ...ArtifactFragment
                                }
                                cursor
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
            """
            + wandb.Artifact._get_gql_artifact_fragment()
        )

        input_query = gql(
            """
            query RunInputArtifacts(
                $entity: String!, $project: String!, $runName: String!, $cursor: String, $perPage: Int,
            ) {
                project(name: $project, entityName: $entity) {
                    run(name: $runName) {
                        inputArtifacts(after: $cursor, first: $perPage) {
                            totalCount
                            edges {
                                node {
                                    ...ArtifactFragment
                                }
                                cursor
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
            """
            + wandb.Artifact._get_gql_artifact_fragment()
        )

        self.run = run
        if mode == "logged":
            self.run_key = "outputArtifacts"
            self.QUERY = output_query
        elif mode == "used":
            self.run_key = "inputArtifacts"
            self.QUERY = input_query
        else:
            raise ValueError("mode must be logged or used")

        variable_values = {
            "entity": run.entity,
            "project": run.project,
            "runName": run.id,
        }

        super().__init__(client, variable_values, per_page)

    @property
    def length(self):
        if self.last_response:
            return self.last_response["project"]["run"][self.run_key]["totalCount"]
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["run"][self.run_key]["pageInfo"][
                "hasNextPage"
            ]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["run"][self.run_key]["edges"][-1][
                "cursor"
            ]
        else:
            return None

    def convert_objects(self):
        return [
            wandb.Artifact._from_attrs(
                r["node"]["artifactSequence"]["project"]["entityName"],
                r["node"]["artifactSequence"]["project"]["name"],
                "{}:v{}".format(
                    r["node"]["artifactSequence"]["name"], r["node"]["versionIndex"]
                ),
                r["node"],
                self.client,
            )
            for r in self.last_response["project"]["run"][self.run_key]["edges"]
        ]


class ArtifactFiles(Paginator):
    QUERY = gql(
        """
        query ArtifactFiles(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!,
            $artifactName: String!
            $fileNames: [String!],
            $fileCursor: String,
            $fileLimit: Int = 50
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    artifact(name: $artifactName) {
                        ...ArtifactFilesFragment
                    }
                }
            }
        }
        %s
    """
        % ARTIFACT_FILES_FRAGMENT
    )

    def __init__(
        self,
        client: Client,
        artifact: "wandb.Artifact",
        names: Optional[Sequence[str]] = None,
        per_page: int = 50,
    ):
        self.artifact = artifact
        variables = {
            "entityName": artifact.source_entity,
            "projectName": artifact.source_project,
            "artifactTypeName": artifact.type,
            "artifactName": artifact.source_name,
            "fileNames": names,
        }
        # The server must advertise at least SDK 0.12.21
        # to get storagePath
        if not client.version_supported("0.12.21"):
            self.QUERY = gql(self.QUERY.loc.source.body.replace("storagePath\n", ""))
        super().__init__(client, variables, per_page)

    @property
    def path(self):
        return [self.artifact.entity, self.artifact.project, self.artifact.name]

    @property
    def length(self):
        return self.artifact.file_count

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifact"]["files"][
                "pageInfo"
            ]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifact"]["files"][
                "edges"
            ][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update({"fileLimit": self.per_page, "fileCursor": self.cursor})

    def convert_objects(self):
        return [
            public.File(self.client, r["node"])
            for r in self.last_response["project"]["artifactType"]["artifact"]["files"][
                "edges"
            ]
        ]

    def __repr__(self):
        return "<ArtifactFiles {} ({})>".format("/".join(self.path), len(self))


def server_supports_artifact_collections_gql_edges(
    client: "RetryingClient", warn: bool = False
) -> bool:
    # TODO: Validate this version
    # Edges were merged into core on Mar 2, 2022: https://github.com/wandb/core/commit/81c90b29eaacfe0a96dc1ebd83c53560ca763e8b
    # CLI version was bumped to "0.12.11" on Mar 3, 2022: https://github.com/wandb/core/commit/328396fa7c89a2178d510a1be9c0d4451f350d7b
    supported = client.version_supported("0.12.11")  # edges were merged on
    if not supported and warn:
        # First local release to include the above is 0.9.50: https://github.com/wandb/local/releases/tag/0.9.50
        wandb.termwarn(
            "W&B Local Server version does not support ArtifactCollection gql edges; falling back to using legacy ArtifactSequence. Please update server to at least version 0.9.50."
        )
    return supported


def artifact_collection_edge_name(server_supports_artifact_collections: bool) -> str:
    return (
        "artifactCollection"
        if server_supports_artifact_collections
        else "artifactSequence"
    )


def artifact_collection_plural_edge_name(
    server_supports_artifact_collections: bool,
) -> str:
    return (
        "artifactCollections"
        if server_supports_artifact_collections
        else "artifactSequences"
    )
