"""Public API: registries search."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from typing_extensions import override
from wandb_gql import gql

from wandb.apis.paginator import Paginator
from wandb.apis.public.utils import gql_compat
from wandb.sdk.artifacts._generated import (
    REGISTRY_VERSIONS_GQL,
    RegistryVersions,
    RegistryVersionsPage,
)
from wandb.sdk.artifacts._graphql_fragments import (
    _gql_registry_fragment,
    omit_artifact_fields,
)
from wandb.sdk.artifacts._validators import remove_registry_prefix
from wandb.sdk.internal.internal_api import Api as InternalApi

from ._utils import ensure_registry_prefix_on_names

if TYPE_CHECKING:
    from wandb_gql import Client

    from wandb.sdk.artifacts.artifact import Artifact


class Registries(Paginator):
    """An lazy iterator of `Registry` objects."""

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
        client: Client,
        organization: str,
        filter: dict[str, Any] | None = None,
        per_page: int | None = 100,
    ):
        self.client = client
        self.organization = organization
        self.filter = ensure_registry_prefix_on_names(filter or {})
        variables = {
            "organization": organization,
            "filters": json.dumps(self.filter),
        }

        super().__init__(client, variables, per_page)

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    def collections(self, filter: dict[str, Any] | None = None) -> Collections:
        return Collections(
            self.client,
            self.organization,
            registry_filter=self.filter,
            collection_filter=filter,
        )

    def versions(self, filter: dict[str, Any] | None = None) -> Versions:
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
                remove_registry_prefix(r["node"]["name"]),
                r["node"],
            )
            for r in self.last_response["organization"]["orgEntity"]["projects"][
                "edges"
            ]
        ]


class Collections(Paginator["ArtifactCollection"]):
    """An lazy iterator of `ArtifactCollection` objects in a Registry."""

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
        client: Client,
        organization: str,
        registry_filter: dict[str, Any] | None = None,
        collection_filter: dict[str, Any] | None = None,
        per_page: int | None = 100,
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

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    def versions(self, filter: dict[str, Any] | None = None) -> Versions:
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


class Versions(Paginator["Artifact"]):
    """An lazy iterator of `Artifact` objects in a Registry."""

    last_response: RegistryVersionsPage | None

    def __init__(
        self,
        client: Client,
        organization: str,
        registry_filter: dict[str, Any] | None = None,
        collection_filter: dict[str, Any] | None = None,
        artifact_filter: dict[str, Any] | None = None,
        per_page: int = 100,
    ):
        self.client = client
        self.organization = organization
        self.registry_filter = registry_filter
        self.collection_filter = collection_filter
        self.artifact_filter = artifact_filter or {}

        # Only omit the `aliases` field on the `ArtifactFragment` fragment,
        # since we don't want to omit it on the `RegistryVersionsPage` fragment.
        omitted_artifact_fields = omit_artifact_fields(api=InternalApi()) | {"aliases"}
        self.QUERY = gql_compat(
            REGISTRY_VERSIONS_GQL,
            omit_fragment_fields={"ArtifactFragment": omitted_artifact_fields},
        )

        variables = {
            "registryFilter": json.dumps(f) if (f := registry_filter) else None,
            "collectionFilter": json.dumps(f) if (f := collection_filter) else None,
            "artifactFilter": json.dumps(f) if (f := artifact_filter) else None,
            "organization": organization,
        }

        super().__init__(client, variables, per_page)

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    @property
    def length(self) -> int | None:
        if self.last_response is None:
            return None
        return len(self.last_response.edges)

    @property
    def more(self) -> bool:
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self) -> str | None:
        if self.last_response is None:
            return None
        return self.last_response.page_info.end_cursor

    @override
    def _update_response(self) -> None:
        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = RegistryVersions.model_validate(data)
        if not (
            (org_data := result.organization)
            and (org_entity_data := org_data.org_entity)
        ):
            raise ValueError(
                f"Organization {self.organization!r} not found. Please verify the organization name is correct."
            )

        try:
            page_data = org_entity_data.artifact_memberships
            self.last_response = RegistryVersionsPage.model_validate(page_data)
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self) -> list[Artifact]:
        from wandb.sdk.artifacts.artifact import Artifact

        if self.last_response is None:
            return []

        nodes = (e.node for e in self.last_response.edges)
        return [
            Artifact._from_attrs(
                project.entity.name,
                project.name,
                f"{collection.name}:v{node.version_index}",
                artifact,
                self.client,
                [alias.alias for alias in node.aliases],
            )
            for node in nodes
            if (
                (collection := node.artifact_collection)
                and (project := collection.project)
                and (artifact := node.artifact)
            )
        ]
