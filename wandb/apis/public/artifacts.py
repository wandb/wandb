"""Public API: artifacts."""

import json
import re
from copy import copy
from typing import TYPE_CHECKING, Any, List, Mapping, Optional, Sequence, Union

from wandb_gql import Client, gql

import wandb
from wandb.apis import public
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import Paginator, SizedPaginator
from wandb.errors.term import termlog
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk.artifacts._graphql_fragments import (
    ARTIFACT_FILES_FRAGMENT,
    ARTIFACTS_TYPES_FRAGMENT,
)
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.lib import deprecate

if TYPE_CHECKING:
    from wandb.apis.public import RetryingClient, Run


class ArtifactTypes(Paginator["ArtifactType"]):
    QUERY = gql(
        """
        query ProjectArtifacts(
            $entityName: String!,
            $projectName: String!,
            $cursor: String,
        ) {{
            project(name: $projectName, entityName: $entityName) {{
                artifactTypes(after: $cursor) {{
                    ...ArtifactTypesFragment
                }}
            }}
        }}
        {}
    """.format(ARTIFACTS_TYPES_FRAGMENT)
    )

    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        per_page: int = 50,
    ):
        self.entity = entity
        self.project = project

        variable_values = {
            "entityName": entity,
            "projectName": project,
        }

        super().__init__(client, variable_values, per_page)

    @property
    def length(self) -> None:
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
            raise ValueError("Could not find artifact type {}".format(self.type))
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


class ArtifactCollections(SizedPaginator["ArtifactCollection"]):
    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        type_name: str,
        per_page: int = 50,
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
            ) {{
                project(name: $projectName, entityName: $entityName) {{
                    artifactType(name: $artifactTypeName) {{
                        artifactCollections: {}(after: $cursor) {{
                            pageInfo {{
                                endCursor
                                hasNextPage
                            }}
                            totalCount
                            edges {{
                                node {{
                                    id
                                    name
                                    description
                                    createdAt
                                }}
                                cursor
                            }}
                        }}
                    }}
                }}
            }}
        """.format(
                artifact_collection_plural_edge_name(
                    server_supports_artifact_collections_gql_edges(client)
                )
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
        organization: Optional[str] = None,
        attrs: Optional[Mapping[str, Any]] = None,
    ):
        self.client = client
        self.entity = entity
        self.project = project
        self._name = name
        self._saved_name = name
        self._type = type
        self._saved_type = type
        self._attrs = attrs
        if self._attrs is None:
            self.load()
        self._aliases = [a["node"]["alias"] for a in self._attrs["aliases"]["edges"]]
        self._description = self._attrs["description"]
        self._created_at = self._attrs["createdAt"]
        self._tags = [a["node"]["name"] for a in self._attrs["tags"]["edges"]]
        self._saved_tags = copy(self._tags)
        self.organization = organization

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
            self._saved_name,
            self._saved_type,
            per_page=per_page,
        )

    @property
    def aliases(self):
        """Artifact Collection Aliases."""
        return self._aliases

    @property
    def created_at(self):
        return self._created_at

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
        ) {{
            project(name: $projectName, entityName: $entityName) {{
                artifactType(name: $artifactTypeName) {{
                    artifactCollection: {}(name: $artifactCollectionName) {{
                        id
                        name
                        description
                        createdAt
                        tags {{
                            edges {{
                                node {{
                                    id
                                    name
                                }}
                            }}
                        }}
                        aliases(after: $cursor, first: $perPage){{
                            edges {{
                                node {{
                                    alias
                                }}
                                cursor
                            }}
                            pageInfo {{
                                endCursor
                                hasNextPage
                            }}
                        }}
                    }}
                    artifactSequence(name: $artifactCollectionName) {{
                        __typename
                    }}
                }}
            }}
        }}
        """.format(
                artifact_collection_edge_name(
                    server_supports_artifact_collections_gql_edges(self.client)
                )
            )
        )
        response = self.client.execute(
            query,
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactTypeName": self._saved_type,
                "artifactCollectionName": self._saved_name,
            },
        )
        if (
            response is None
            or response.get("project") is None
            or response["project"].get("artifactType") is None
            or response["project"]["artifactType"].get("artifactCollection") is None
        ):
            raise ValueError("Could not find artifact type {}".format(self._saved_type))
        sequence = response["project"]["artifactType"]["artifactSequence"]
        self._is_sequence = (
            sequence is not None and sequence["__typename"] == "ArtifactSequence"
        )

        if self._attrs is None:
            self._attrs = response["project"]["artifactType"]["artifactCollection"]
        return self._attrs

    def change_type(self, new_type: str) -> None:
        """Deprecated, change type directly with `save` instead."""
        deprecate.deprecate(
            field_name=deprecate.Deprecated.artifact_collection__change_type,
            warning_message="ArtifactCollection.change_type(type) is deprecated, use ArtifactCollection.save() instead.",
        )

        if not self.is_sequence():
            raise ValueError("Artifact collection needs to be a sequence")
        termlog(
            f"Changing artifact collection type of {self._saved_type} to {new_type}"
        )
        template = """
            mutation MoveArtifactCollection(
                $artifactSequenceID: ID!
                $destinationArtifactTypeName: String!
            ) {
                moveArtifactSequence(
                input: {
                    artifactSequenceID: $artifactSequenceID
                    destinationArtifactTypeName: $destinationArtifactTypeName
                }
                ) {
                artifactCollection {
                    id
                    name
                    description
                    __typename
                }
                }
            }
            """
        variable_values = {
            "artifactSequenceID": self.id,
            "destinationArtifactTypeName": new_type,
        }
        mutation = gql(template)
        self.client.execute(mutation, variable_values=variable_values)
        self._saved_type = new_type
        self._type = new_type

    def is_sequence(self) -> bool:
        """Return whether the artifact collection is a sequence."""
        return self._is_sequence

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

    @property
    def description(self):
        """A description of the artifact collection."""
        return self._description

    @description.setter
    def description(self, description: Optional[str]) -> None:
        self._description = description

    @property
    def tags(self):
        """The tags associated with the artifact collection."""
        return self._tags

    @tags.setter
    def tags(self, tags: List[str]) -> None:
        if any(not re.match(r"^[-\w]+([ ]+[-\w]+)*$", tag) for tag in tags):
            raise ValueError(
                "Tags must only contain alphanumeric characters or underscores separated by spaces or hyphens"
            )
        self._tags = tags

    @property
    def name(self):
        """The name of the artifact collection."""
        return self._name

    @name.setter
    def name(self, name: List[str]) -> None:
        self._name = name

    @property
    def type(self):
        """The type of the artifact collection."""
        return self._type

    @type.setter
    def type(self, type: List[str]) -> None:
        if not self.is_sequence():
            raise ValueError(
                "Type can only be changed if the artifact collection is a sequence."
            )
        self._type = type

    def _update_collection(self):
        mutation = gql("""
            mutation UpdateArtifactCollection(
                $artifactSequenceID: ID!
                $name: String
                $description: String
            ) {
                updateArtifactSequence(
                input: {
                    artifactSequenceID: $artifactSequenceID
                    name: $name
                    description: $description
                }
                ) {
                artifactCollection {
                    id
                    name
                    description
                }
                }
            }
        """)

        variable_values = {
            "artifactSequenceID": self.id,
            "name": self._name,
            "description": self.description,
        }
        self.client.execute(mutation, variable_values=variable_values)
        self._saved_name = self._name

    def _update_collection_type(self):
        type_mutation = gql("""
            mutation MoveArtifactCollection(
                $artifactSequenceID: ID!
                $destinationArtifactTypeName: String!
            ) {
                moveArtifactSequence(
                input: {
                    artifactSequenceID: $artifactSequenceID
                    destinationArtifactTypeName: $destinationArtifactTypeName
                }
                ) {
                artifactCollection {
                    id
                    name
                    description
                    __typename
                }
                }
            }
            """)

        variable_values = {
            "artifactSequenceID": self.id,
            "destinationArtifactTypeName": self._type,
        }
        self.client.execute(type_mutation, variable_values=variable_values)
        self._saved_type = self._type

    def _update_portfolio(self):
        mutation = gql("""
            mutation UpdateArtifactPortfolio(
                $artifactPortfolioID: ID!
                $name: String
                $description: String
            ) {
                updateArtifactPortfolio(
                input: {
                    artifactPortfolioID: $artifactPortfolioID
                    name: $name
                    description: $description
                }
                ) {
                artifactCollection {
                    id
                    name
                    description
                }
                }
            }
        """)
        variable_values = {
            "artifactPortfolioID": self.id,
            "name": self._name,
            "description": self.description,
        }
        self.client.execute(mutation, variable_values=variable_values)
        self._saved_name = self._name

    def _add_tags(self, tags_to_add):
        add_mutation = gql(
            """
            mutation CreateArtifactCollectionTagAssignments(
                $entityName: String!
                $projectName: String!
                $artifactCollectionName: String!
                $tags: [TagInput!]!
            ) {
                createArtifactCollectionTagAssignments(
                input: {
                    entityName: $entityName
                    projectName: $projectName
                    artifactCollectionName: $artifactCollectionName
                    tags: $tags
                }
                ) {
                tags {
                    id
                    name
                    tagCategoryName
                }
                }
            }
            """
        )
        self.client.execute(
            add_mutation,
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactCollectionName": self._saved_name,
                "tags": [
                    {
                        "tagName": tag,
                    }
                    for tag in tags_to_add
                ],
            },
        )

    def _delete_tags(self, tags_to_delete):
        delete_mutation = gql(
            """
            mutation DeleteArtifactCollectionTagAssignments(
                $entityName: String!
                $projectName: String!
                $artifactCollectionName: String!
                $tags: [TagInput!]!
            ) {
                deleteArtifactCollectionTagAssignments(
                input: {
                    entityName: $entityName
                    projectName: $projectName
                    artifactCollectionName: $artifactCollectionName
                    tags: $tags
                }
                ) {
                success
                }
            }
            """
        )
        self.client.execute(
            delete_mutation,
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactCollectionName": self._saved_name,
                "tags": [
                    {
                        "tagName": tag,
                    }
                    for tag in tags_to_delete
                ],
            },
        )

    def save(self) -> None:
        """Persist any changes made to the artifact collection."""
        if self.is_sequence():
            self._update_collection()

            if self._saved_type != self._type:
                self._update_collection_type()
        else:
            self._update_portfolio()

        tags_to_add = set(self._tags) - set(self._saved_tags)
        tags_to_delete = set(self._saved_tags) - set(self._tags)
        if len(tags_to_add) > 0:
            self._add_tags(tags_to_add)
        if len(tags_to_delete) > 0:
            self._delete_tags(tags_to_delete)
        self._saved_tags = copy(self._tags)

    def __repr__(self):
        return f"<ArtifactCollection {self._name} ({self._type})>"


class Artifacts(SizedPaginator["wandb.Artifact"]):
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
        tags: Optional[Union[str, List[str]]] = None,
    ):
        from wandb.sdk.artifacts.artifact import _gql_artifact_fragment

        self.entity = entity
        self.collection_name = collection_name
        self.type = type
        self.project = project
        self.filters = {"state": "COMMITTED"} if filters is None else filters
        self.tags = [tags] if isinstance(tags, str) else tags
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
                _gql_artifact_fragment(),
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
        collection = self.last_response["project"]["artifactType"]["artifactCollection"]
        artifact_edges = collection.get("artifacts", {}).get("edges", [])
        artifacts = (
            wandb.Artifact._from_attrs(
                self.entity,
                self.project,
                self.collection_name + ":" + a["version"],
                a["node"],
                self.client,
            )
            for a in artifact_edges
        )
        required_tags = set(self.tags or [])
        return [
            artifact for artifact in artifacts if required_tags.issubset(artifact.tags)
        ]


class RunArtifacts(SizedPaginator["wandb.Artifact"]):
    def __init__(self, client: Client, run: "Run", mode="logged", per_page: int = 50):
        from wandb.sdk.artifacts.artifact import _gql_artifact_fragment

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
            + _gql_artifact_fragment()
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
            + _gql_artifact_fragment()
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


class ArtifactFiles(SizedPaginator["public.File"]):
    ARTIFACT_VERSION_FILES_QUERY = gql(
        f"""
        query ArtifactFiles(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!,
            $artifactName: String!
            $fileNames: [String!],
            $fileCursor: String,
            $fileLimit: Int = 50
        ) {{
            project(name: $projectName, entityName: $entityName) {{
                artifactType(name: $artifactTypeName) {{
                    artifact(name: $artifactName) {{
                        files(names: $fileNames, after: $fileCursor, first: $fileLimit) {{
                            ...FilesFragment
                        }}
                    }}
                }}
            }}
        }}
        {ARTIFACT_FILES_FRAGMENT}
    """
    )

    ARTIFACT_COLLECTION_MEMBERSHIP_FILES_QUERY = gql(
        f"""
        query ArtifactCollectionMembershipFiles(
            $entityName: String!,
            $projectName: String!,
            $artifactName: String!,
            $artifactVersionIndex: String!,
            $fileNames: [String!],
            $fileCursor: String,
            $fileLimit: Int = 50
        ) {{
            project(name: $projectName, entityName: $entityName) {{
                artifactCollection(name: $artifactName) {{
                    artifactMembership (aliasName: $artifactVersionIndex) {{
                        files(names: $fileNames, after: $fileCursor, first: $fileLimit) {{
                            ...FilesFragment
                        }}
                    }}
                }}
            }}
        }}
        {ARTIFACT_FILES_FRAGMENT}
        """
    )

    def __init__(
        self,
        client: Client,
        artifact: "wandb.Artifact",
        names: Optional[Sequence[str]] = None,
        per_page: int = 50,
    ):
        self.query_via_membership = InternalApi()._check_server_feature_with_fallback(
            ServerFeature.ARTIFACT_COLLECTION_MEMBERSHIP_FILES
        )
        self.artifact = artifact
        variables = {
            "entityName": artifact.source_entity,
            "projectName": artifact.source_project,
            "artifactTypeName": artifact.type,
            "artifactName": artifact.source_name,
            "fileNames": names,
        }
        if self.query_via_membership:
            self.QUERY = self.ARTIFACT_COLLECTION_MEMBERSHIP_FILES_QUERY
            variables = {
                "entityName": artifact.entity,
                "projectName": artifact.project,
                "artifactName": artifact.name.split(":")[0],
                "artifactVersionIndex": artifact.version,
                "fileNames": names,
            }
        else:
            self.QUERY = self.ARTIFACT_VERSION_FILES_QUERY
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
            if self.query_via_membership:
                return self.last_response["project"]["artifactCollection"][
                    "artifactMembership"
                ]["files"]["pageInfo"]["hasNextPage"]
            return self.last_response["project"]["artifactType"]["artifact"]["files"][
                "pageInfo"
            ]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            if self.query_via_membership:
                return self.last_response["project"]["artifactCollection"][
                    "artifactMembership"
                ]["files"]["edges"][-1]["cursor"]
            return self.last_response["project"]["artifactType"]["artifact"]["files"][
                "edges"
            ][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update({"fileLimit": self.per_page, "fileCursor": self.cursor})

    def convert_objects(self):
        if self.query_via_membership:
            return [
                public.File(self.client, r["node"])
                for r in self.last_response["project"]["artifactCollection"][
                    "artifactMembership"
                ]["files"]["edges"]
            ]
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
