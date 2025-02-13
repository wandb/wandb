"""Public API: registries."""

import json
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from wandb_gql import Client

from wandb_gql import gql

import wandb
from wandb.apis.paginator import Paginator
from wandb.apis.public.artifacts import ArtifactCollection
from wandb.sdk.artifacts._graphql_fragments import (
    _gql_artifact_fragment,
    _gql_registry_fragment,
)
from wandb.sdk.artifacts._validators import REGISTRY_PREFIX


class Registries(Paginator):
    """Iterator that returns Registries."""

    def __init__(
        self,
        client: "Client",
        organization: str,
        filter: Optional[Dict[str, Any]] = None,
        per_page: Optional[int] = 100,
    ):
        self.client = client
        self.organization = organization
        self.filter = _inject_registry_prefix_in_name(filter or {})
        self.QUERY = gql(
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


class Registry:
    """A single registry in the Registry."""

    def __init__(
        self,
        client: "Client",
        organization: str,
        entity: str,
        full_name: str,
        attrs: Dict[str, Any],
    ):
        self.client = client
        self._full_name = full_name
        self._name = full_name.replace(REGISTRY_PREFIX, "")
        self._entity = entity
        self._organization = organization
        self._description = attrs.get("description", "")
        self._allow_all_artifact_types = attrs.get(
            "allowAllArtifactTypesInRegistry", False
        )
        self._artifact_types = [
            t["node"]["name"] for t in attrs.get("artifactTypes", {}).get("edges", [])
        ]
        self._id = attrs.get("id", "")
        self._created_at = attrs.get("createdAt", "")
        self._updated_at = attrs.get("updatedAt", "")

    @property
    def full_name(self):
        return self._full_name

    @property
    def name(self):
        return self._name

    @property
    def entity(self):
        return self._entity

    @property
    def organization(self):
        return self._organization

    @property
    def description(self):
        return self._description

    @property
    def allow_all_artifact_types(self):
        return self._allow_all_artifact_types

    @property
    def artifact_types(self):
        return self._artifact_types

    @property
    def created_at(self):
        return self._created_at

    @property
    def updated_at(self):
        return self._updated_at

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


def _inject_registry_prefix_in_name(query, in_name=False, skip_transform=False):
    """Traverse the filter to prepend the `name` key value with the registry prefix unless the value is a regex.

    - in_name: True if we are under a "name" key (or propagating from one).
    - skip_transform: True if we should not transform string values (e.g. within a regex).

    EX: {"name": "model"} -> {"name": "wandb-registry-model"}
    """
    if isinstance(query, dict):
        new_dict = {}
        for key, value in query.items():
            if key == "name":
                # If the value for "name" is a dict and it contains "$regex",
                # then we want to leave it unchanged.
                if isinstance(value, dict) and "$regex" in value:
                    new_dict[key] = value
                else:
                    # Otherwise, process with in_name True.
                    new_dict[key] = _inject_registry_prefix_in_name(
                        value, in_name=True, skip_transform=False
                    )
            elif key == "$regex":
                # For regex operator, we skip transformation of its value.
                new_dict[key] = value
            else:
                # For any other key, propagate the in_name and skip_transform flags as-is.
                new_dict[key] = _inject_registry_prefix_in_name(
                    value, in_name=in_name, skip_transform=skip_transform
                )
        return new_dict
    elif isinstance(query, list):
        return [
            _inject_registry_prefix_in_name(
                item, in_name=in_name, skip_transform=skip_transform
            )
            for item in query
        ]
    elif isinstance(query, str):
        # If skip_transform is active, don't transform the string.
        if skip_transform:
            return query
        if in_name:
            return REGISTRY_PREFIX + query
        else:
            return query
    else:
        # For numbers, booleans, None, etc., just return the value unchanged.
        return query
