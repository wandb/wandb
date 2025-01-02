"""Public API: regsitries."""

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

from wandb_gql import gql

import wandb
from wandb.apis.paginator import Paginator
from wandb.apis.public.artifacts import ArtifactCollection


class Registries:
    def __init__(
        self, client, organization_name: str, filter: Optional[Dict[str, Any]] = None
    ):
        self.client = client
        self.organization_name = organization_name
        self.filter = filter or {}

    def collections(self, filter: Optional[Dict[str, Any]] = None) -> "Collections":
        return Collections(self.client, self.filter, filter)

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        query = gql("""
            query Registries($filter: JSONString) {
                registries(filter: $filter) {
                    edges {
                        node {
                            id
                            name
                            description
                        }
                    }
                }
            }
        """)

        response = self.client.execute(
            query, variable_values={"filter": json.dumps(self.filter)}
        )
        return (edge["node"] for edge in response["registries"]["edges"])


class Collections(Paginator):
    def __init__(
        self,
        client,
        organization_name: str,
        registry_filter: Optional[Dict[str, Any]] = None,
        collection_filter: Optional[Dict[str, Any]] = None,
        per_page: Optional[int] = 100,
    ):
        self.client = client
        self.organization_name = organization_name
        self.registry_filter = registry_filter
        self.collection_filter = collection_filter or {}
        variables = {
            "registryFilter": json.dumps(self.registry_filter)
            if self.registry_filter
            else None,
            "collectionFilter": json.dumps(self.collection_filter),
        }

        # TODO: Make this query have all the fields we need
        self.QUERY = gql("""
            query Collections($registryFilter: JSONString, $collectionFilter: JSONString) {{
                organization(organizationName: $organizationName) {{
                    id
                    name
                    artifactCollections(registryFilter: $registryFilter, collectionFilter: $collectionFilter) {}(after: $cursor) {{
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
                                tags {{
                                    edges {{
                                        node {{
                                            name
                                        }}
                                    }}
                                }}
                            }}
                            cursor
                        }}
                    }}
                }}
            }}
        """)

        super().__init__(client, variables, per_page)

    def versions(self, filter: Optional[Dict[str, Any]] = None) -> "Versions":
        return Versions(
            self.client, self.registry_filter, self.collection_filter, filter
        )

    @property
    def length(self):
        # TODO: Implement this for real
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollections"][
                "totalCount"
            ]
        else:
            return None

    @property
    def more(self):
        # TODO: Implement this for real
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollections"][
                "pageInfo"
            ]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        # TODO: Implement this for real
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollections"][
                "edges"
            ][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update({"cursor": self.cursor})

    def convert_objects(self):
        # TODO: Implement this for real
        return [
            ArtifactCollection(
                self.client,
                self.entity,
                self.project,
                r["node"]["colle"],
                self.type_name,
            )
            for r in self.last_response["registries"]["edges"]
        ]


class Versions(Paginator):
    def __init__(
        self,
        client,
        registry_filter: Optional[Dict[str, Any]] = None,
        collection_filter: Optional[Dict[str, Any]] = None,
        artifact_filter: Optional[Dict[str, Any]] = None,
        per_page: int = 100,
    ):
        self.client = client
        self.registry_filter = registry_filter
        self.collection_filter = collection_filter
        self.artifact_filter = artifact_filter or {}

        # TODO: Make this query have all the fields we need
        self.QUERY = gql(
            """
            query Versions($registryFilter: JSONString, $collectionFilter: JSONString, $artifactFilter: JSONString, $cursor: String, $perPage: Int) {{
                organization(organizationName: $organizationName) {{
                    artifactMemberships(registryName: $registryName, collectionName: $collectionName, artifactFilter: $artifactFilter, after: $cursor, first: $perPage) {{
                        pageInfo {{
                            endCursor
                            hasNextPage
                        }}
                        totalCount
                        edges {{
                            node {{
                                version
                            }}
                        }}
                    }}
                }}
            }}
            """
        )

        variables = {
            "registryFilter": json.dumps(self.registry_filter)
            if self.registry_filter
            else None,
            "collectionFilter": json.dumps(self.collection_filter)
            if self.collection_filter
            else None,
            "artifactFilter": json.dumps(self.artifact_filter),
        }

        super().__init__(client, variables, per_page)

    @property
    def length(self):
        # TODO: Implement this for real
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollection"][
                "artifacts"
            ]["totalCount"]
        else:
            return None

    @property
    def more(self):
        # TODO: Implement this for real
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollection"][
                "artifacts"
            ]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        # TODO: Implement this with real data
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollection"][
                "artifacts"
            ]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self):
        # TODO: Implement this with real data
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
