"""Public API: registries search."""

import json
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from wandb_gql import Client

from wandb_gql import gql

import wandb
from wandb.apis.paginator import Paginator
from wandb.sdk.artifacts._graphql_fragments import (
    _gql_artifact_fragment,
    _gql_registry_fragment,
)

from .utils import _ensure_registry_prefix_on_names


class Registries(Paginator):
    """Iterator that returns Registries."""

    QUERY = gql(
        """
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
                                ...RegistryFragment
                            }
                        }
                    }
                }
            }
        }
        """
        + _gql_registry_fragment()
    )

    def __init__(
        self,
        client: "Client",
        organization: str,
        filter: Optional[Dict[str, Any]] = None,
        per_page: Optional[int] = 100,
    ):
        self.client = client
        self.organization = organization
        self.filter = _ensure_registry_prefix_on_names(filter or {})
        variables = {
            "organization": organization,
            "filters": json.dumps(self.filter),
        }

        super().__init__(client, variables, per_page)

    def __bool__(self):
        return bool(self.objects)

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    def collections(self, filter: Optional[Dict[str, Any]] = None) -> "Collections":
        return Collections(
            self.client,
            self.organization,
            registry_filter=self.filter,
            collection_filter=filter,
        )

    def versions(self, filter: Optional[Dict[str, Any]] = None) -> "Versions":
        return Versions(
            self.client,
            self.organization,
            registry_filter=self.filter,
            collection_filter=None,
            artifact_filter=filter,
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
        if not self.last_response:
            return []
        if (
            not self.last_response["organization"]
            or not self.last_response["organization"]["orgEntity"]
        ):
            raise ValueError(
                f"Organization '{self.organization}' not found. Please verify the organization name is correct"
            )

        from wandb.apis.public.registries.registry import Registry

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


class Collections(Paginator):
    """Iterator that returns Artifact collections in the Registry."""

    QUERY = gql(
        """
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
        """
    )

    def __init__(
        self,
        client: "Client",
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
            "registryFilter": (
                json.dumps(self.registry_filter) if self.registry_filter else None
            ),
            "collectionFilter": (
                json.dumps(self.collection_filter) if self.collection_filter else None
            ),
            "organization": self.organization,
            "collectionTypes": ["PORTFOLIO"],
            "perPage": per_page,
        }

        super().__init__(client, variables, per_page)

    def __bool__(self):
        return len(self) > 0 or len(self.objects) > 0

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    def versions(self, filter: Optional[Dict[str, Any]] = None) -> "Versions":
        return Versions(
            self.client,
            self.organization,
            registry_filter=self.registry_filter,
            collection_filter=self.collection_filter,
            artifact_filter=filter,
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
        from wandb.apis.public import ArtifactCollection

        if not self.last_response:
            return []
        if (
            not self.last_response["organization"]
            or not self.last_response["organization"]["orgEntity"]
        ):
            raise ValueError(
                f"Organization '{self.organization}' not found. Please verify the organization name is correct"
            )

        return [
            ArtifactCollection(
                self.client,
                r["node"]["project"]["entity"]["name"],
                r["node"]["project"]["name"],
                r["node"]["name"],
                r["node"]["defaultArtifactType"]["name"],
                self.organization,
                r["node"],
                is_sequence=False,
            )
            for r in self.last_response["organization"]["orgEntity"][
                "artifactCollections"
            ]["edges"]
        ]


class Versions(Paginator):
    """Iterator that returns Artifact versions in the Registry."""

    def __init__(
        self,
        client: "Client",
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
            "registryFilter": (
                json.dumps(self.registry_filter) if self.registry_filter else None
            ),
            "collectionFilter": (
                json.dumps(self.collection_filter) if self.collection_filter else None
            ),
            "artifactFilter": (
                json.dumps(self.artifact_filter) if self.artifact_filter else None
            ),
            "organization": self.organization,
        }

        super().__init__(client, variables, per_page)

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    def __bool__(self):
        return len(self) > 0 or len(self.objects) > 0

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
        if not self.last_response:
            return []
        if (
            not self.last_response["organization"]
            or not self.last_response["organization"]["orgEntity"]
        ):
            raise ValueError(
                f"Organization '{self.organization}' not found. Please verify the organization name is correct"
            )

        artifacts = (
            wandb.Artifact._from_attrs(
                a["node"]["artifactCollection"]["project"]["entity"]["name"],
                a["node"]["artifactCollection"]["project"]["name"],
                a["node"]["artifactCollection"]["name"]
                + ":v"
                + str(a["node"]["versionIndex"]),
                a["node"]["artifact"],
                self.client,
                [alias["alias"] for alias in a["node"]["aliases"]],
            )
            for a in self.last_response["organization"]["orgEntity"][
                "artifactMemberships"
            ]["edges"]
        )
        return artifacts
