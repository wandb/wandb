"""Public API: registries."""

import json
from typing import Any, Dict, Optional

from wandb_gql import gql

import wandb
from wandb.apis.attrs import Attrs
from wandb.apis.paginator import Paginator
from wandb.apis.public.artifacts import ArtifactCollection
from wandb.sdk.artifacts.graphql_fragments import _gql_artifact_fragment


class Registries(Paginator):
    """Iterator that returns Registries."""

    def __init__(
        self,
        client,
        organization: str,
        filter: Optional[Dict[str, Any]] = None,
        per_page: Optional[int] = 100,
    ):
        self.client = client
        self.organization = organization
        self.filter = filter or {}
        self.QUERY = gql("""
            query Registries($organization: String!, $filters: JSONString, $cursor: String, $perPage: Int) {
                organization(name: $organization) {
                    orgEntity {
                        name
                        projects(filters: $filters, after: $cursor, first: $perPage) {
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                            edges {
                                node {
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
                                }
                            }
                        }
                    }
                }
            }
        """)
        variables = {
            "organization": organization,
            "filters": json.dumps(self.filter),
        }

        super().__init__(client, variables, per_page)

    def __bool__(self):
        return len(self) > 0

    def collections(self, filter: Optional[Dict[str, Any]] = None) -> "Collections":
        return Collections(self.client, self.organization, self.filter, filter)

    def versions(self, filter: Optional[Dict[str, Any]] = None) -> "Versions":
        return Versions(
            self.client,
            self.organization,
            self.filter,
            None,
            filter,
        )

    @property
    def length(self):
        if self.last_response:
            return len(
                self.last_response["organization"]["orgEntity"]["projects"]["edges"]
            )
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["organization"]["orgEntity"]["projects"][
                "pageInfo"
            ]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["organization"]["orgEntity"]["projects"][
                "pageInfo"
            ]["endCursor"]
        else:
            return None

    def convert_objects(self):
        return [
            Registry(
                self.client,
                self.organization,
                self.last_response["organization"]["orgEntity"]["name"],
                r["node"]["name"],
                r["node"],
            )
            for r in self.last_response["organization"]["orgEntity"]["projects"][
                "edges"
            ]
        ]


class Registry(Attrs):
    """A single registry in the Registry."""

    def __init__(self, client, organization, entity, project, attrs):
        self.client = client
        self.full_name = project
        self.name = self.full_name.replace("wandb-registry-", "")
        self.entity = entity
        self.organization = organization
        self.description = attrs.get("description", "")
        self.allow_all_artifact_types = attrs.get(
            "allowAllArtifactTypesInRegistry", False
        )
        self.artifact_types = [
            t["node"]["name"] for t in attrs.get("artifactTypes", {}).get("edges", [])
        ]

    @property
    def path(self):
        return [self.entity, self.name]

    def collections(self, filter: Optional[Dict[str, Any]] = None):
        registry_filter = {
            "name": self.full_name,
        }
        return Collections(self.client, self.organization, registry_filter, filter)

    def versions(self, filter: Optional[Dict[str, Any]] = None):
        registry_filter = {
            "name": self.full_name,
        }
        return Versions(self.client, self.organization, registry_filter, None, filter)


class Collections(Paginator):
    """Iterator that returns Artifact collections in the Registry."""

    def __init__(
        self,
        client,
        organization: str,
        registry_filter: Optional[Dict[str, Any]] = None,
        collection_filter: Optional[Dict[str, Any]] = None,
        per_page: Optional[int] = 100,
    ):
        self.client = client
        self.organization = organization
        self.registry_filter = registry_filter
        self.collection_filter = collection_filter or {}

        variables = {
            "registryFilter": json.dumps(self.registry_filter)
            if self.registry_filter
            else None,
            "collectionFilter": json.dumps(self.collection_filter)
            if self.collection_filter
            else None,
            "organization": self.organization,
            "collectionTypes": ["PORTFOLIO"],
            "perPage": per_page,
        }

        self.QUERY = gql("""
            query Collections(
                $organization: String!,
                $registryFilter: JSONString,
                $collectionFilter: JSONString,
                $collectionTypes: [ArtifactCollectionType!],
                $cursor: String,
                $perPage: Int
            ) {
                organization(name: $organization) {
                    orgEntity {
                        name
                        artifactCollections(
                            projectFilters: $registryFilter,
                            filters: $collectionFilter,
                            collectionTypes: $collectionTypes,
                            after: $cursor,
                            first: $perPage
                        ) {
                            totalCount
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                            edges {
                                cursor
                                node {
                                    id
                                    name
                                    description
                                    createdAt
                                    tags {
                                        edges {
                                            node {
                                                name
                                            }
                                        }
                                    }
                                    project {
                                        name
                                        entity {
                                            name
                                        }
                                    }
                                    defaultArtifactType {
                                        name
                                    }
                                    aliases {
                                        edges {
                                            node {
                                                alias
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        """)

        super().__init__(client, variables, per_page)

    def __bool__(self):
        return len(self) > 0

    def versions(self, filter: Optional[Dict[str, Any]] = None) -> "Versions":
        return Versions(
            self.client,
            self.organization,
            self.registry_filter,
            self.collection_filter,
            filter,
        )

    @property
    def length(self):
        if self.last_response:
            return self.last_response["organization"]["orgEntity"][
                "artifactCollections"
            ]["totalCount"]
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["organization"]["orgEntity"][
                "artifactCollections"
            ]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["organization"]["orgEntity"][
                "artifactCollections"
            ]["pageInfo"]["endCursor"]
        else:
            return None

    def convert_objects(self):
        return [
            ArtifactCollection(
                self.client,
                r["node"]["project"]["entity"]["name"],
                r["node"]["project"]["name"],
                r["node"]["name"],
                r["node"]["defaultArtifactType"]["name"],
                self.organization,
                r["node"],
            )
            for r in self.last_response["organization"]["orgEntity"][
                "artifactCollections"
            ]["edges"]
        ]


class Versions(Paginator):
    """Iterator that returns Artifact versions in the Registry."""

    def __init__(
        self,
        client,
        organization: str,
        registry_filter: Optional[Dict[str, Any]] = None,
        collection_filter: Optional[Dict[str, Any]] = None,
        artifact_filter: Optional[Dict[str, Any]] = None,
        per_page: int = 100,
    ):
        self.client = client
        self.organization = organization
        self.registry_filter = registry_filter
        self.collection_filter = collection_filter
        self.artifact_filter = artifact_filter or {}

        self.QUERY = gql(
            """
            query Versions(
                $organization: String!,
                $registryFilter: JSONString,
                $collectionFilter: JSONString,
                $artifactFilter: JSONString,
                $cursor: String,
                $perPage: Int
            ) {
                organization(name: $organization) {
                    orgEntity {
                        name
                        artifactMemberships(
                            projectFilters: $registryFilter,
                            collectionFilters: $collectionFilter,
                            filters: $artifactFilter,
                            after: $cursor,
                            first: $perPage
                        ) {
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                            edges {
                                node {
                                    artifactCollection {
                                        project {
                                            name
                                            entity {
                                                name
                                            }
                                        }
                                        name
                                    }
                                    versionIndex
                                    artifact {
                                        ...ArtifactFragment
                                    }
                                    aliases {
                                        alias
                                    }
                                }
                            }
                        }
                    }
                }
            }
            """
            + _gql_artifact_fragment(include_aliases=False)
        )

        variables = {
            "registryFilter": json.dumps(self.registry_filter)
            if self.registry_filter
            else None,
            "collectionFilter": json.dumps(self.collection_filter)
            if self.collection_filter
            else None,
            "artifactFilter": json.dumps(self.artifact_filter)
            if self.artifact_filter
            else None,
            "organization": self.organization,
        }

        super().__init__(client, variables, per_page)

    def __bool__(self):
        return len(self) > 0

    @property
    def length(self):
        if self.last_response:
            return len(
                self.last_response["organization"]["orgEntity"]["artifactMemberships"][
                    "edges"
                ]
            )
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["organization"]["orgEntity"][
                "artifactMemberships"
            ]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["organization"]["orgEntity"][
                "artifactMemberships"
            ]["pageInfo"]["endCursor"]
        else:
            return None

    def convert_objects(self):
        artifacts = (
            wandb.Artifact._from_attrs(
                a["node"]["artifactCollection"]["project"]["entity"]["name"],
                a["node"]["artifactCollection"]["project"]["name"],
                a["node"]["artifactCollection"]["name"]
                + ":v"
                + str(a["node"]["versionIndex"]),
                a["node"]["artifact"],
                self.client,
                a["node"]["aliases"],
            )
            for a in self.last_response["organization"]["orgEntity"][
                "artifactMemberships"
            ]["edges"]
        )
        return artifacts
