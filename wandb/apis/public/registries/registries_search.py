"""Public API: registries search."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from typing_extensions import override
from wandb_gql import gql

from wandb._analytics import tracked
from wandb.apis.paginator import Paginator
from wandb.apis.public.utils import gql_compat
from wandb.sdk.artifacts._generated import (
    FETCH_REGISTRIES_GQL,
    REGISTRY_COLLECTIONS_GQL,
    REGISTRY_VERSIONS_GQL,
    ArtifactCollectionType,
    FetchRegistries,
    RegistriesPage,
    RegistryCollections,
    RegistryCollectionsPage,
    RegistryVersions,
    RegistryVersionsPage,
)
from wandb.sdk.artifacts._gqlutils import omit_artifact_fields
from wandb.sdk.artifacts._validators import FullArtifactPath, remove_registry_prefix

from ._utils import ensure_registry_prefix_on_names

if TYPE_CHECKING:
    from wandb_gql import Client

    from wandb.sdk.artifacts.artifact import Artifact


class Registries(Paginator):
    """An lazy iterator of `Registry` objects."""

    QUERY = gql(FETCH_REGISTRIES_GQL)

    last_response: RegistriesPage | None
    _last_org_entity: str | None

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

        self._last_org_entity = None

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    @tracked
    def collections(self, filter: dict[str, Any] | None = None) -> Collections:
        return Collections(
            client=self.client,
            organization=self.organization,
            registry_filter=self.filter,
            collection_filter=filter,
        )

    @tracked
    def versions(self, filter: dict[str, Any] | None = None) -> Versions:
        return Versions(
            client=self.client,
            organization=self.organization,
            registry_filter=self.filter,
            collection_filter=None,
            artifact_filter=filter,
        )

    @property
    def length(self):
        if self.last_response is None:
            return None
        return len(self.last_response.edges)

    @property
    def more(self):
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self):
        if self.last_response is None:
            return None
        return self.last_response.page_info.end_cursor

    @override
    def _update_response(self) -> None:
        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = FetchRegistries.model_validate(data)
        if not ((org := result.organization) and (org_entity := org.org_entity)):
            raise ValueError(
                f"Organization {self.organization!r} not found. Please verify the organization name is correct."
            )

        try:
            page_data = org_entity.projects
            self.last_response = RegistriesPage.model_validate(page_data)
            self._last_org_entity = org_entity.name
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self):
        from wandb.apis.public.registries.registry import Registry

        if (self.last_response is None) or (self._last_org_entity is None):
            return []

        nodes = (e.node for e in self.last_response.edges)
        return [
            Registry(
                client=self.client,
                organization=self.organization,
                entity=self._last_org_entity,
                name=remove_registry_prefix(node.name),
                attrs=node.model_dump(),
            )
            for node in nodes
        ]


class Collections(Paginator["ArtifactCollection"]):
    """An lazy iterator of `ArtifactCollection` objects in a Registry."""

    QUERY = gql(REGISTRY_COLLECTIONS_GQL)

    last_response: RegistryCollectionsPage | None

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
            "registryFilter": json.dumps(f) if (f := registry_filter) else None,
            "collectionFilter": json.dumps(f) if (f := collection_filter) else None,
            "organization": organization,
            "collectionTypes": [ArtifactCollectionType.PORTFOLIO],
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

    @tracked
    def versions(self, filter: dict[str, Any] | None = None) -> Versions:
        return Versions(
            client=self.client,
            organization=self.organization,
            registry_filter=self.registry_filter,
            collection_filter=self.collection_filter,
            artifact_filter=filter,
        )

    @property
    def length(self):
        if self.last_response is None:
            return None
        return self.last_response.total_count

    @property
    def more(self):
        if self.last_response is None:
            return True
        return self.last_response.page_info.has_next_page

    @property
    def cursor(self):
        if self.last_response is None:
            return None
        return self.last_response.page_info.end_cursor

    @override
    def _update_response(self) -> None:
        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = RegistryCollections.model_validate(data)
        if not (
            (org_data := result.organization)
            and (org_entity_data := org_data.org_entity)
        ):
            raise ValueError(
                f"Organization {self.organization!r} not found. Please verify the organization name is correct."
            )

        try:
            page_data = org_entity_data.artifact_collections
            self.last_response = RegistryCollectionsPage.model_validate(page_data)
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def convert_objects(self):
        from wandb.apis.public import ArtifactCollection

        if self.last_response is None:
            return []

        nodes = (e.node for e in self.last_response.edges)
        return [
            ArtifactCollection(
                client=self.client,
                entity=project.entity.name,
                project=project.name,
                name=node.name,
                type=node.default_artifact_type.name,
                organization=self.organization,
                attrs=node.model_dump(),
                is_sequence=False,
            )
            for node in nodes
            if (project := node.project)
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

        self.QUERY = gql_compat(
            REGISTRY_VERSIONS_GQL, omit_fields=omit_artifact_fields(client)
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
                path=FullArtifactPath(
                    prefix=project.entity.name,
                    project=project.name,
                    name=f"{collection.name}:v{node.version_index}",
                ),
                attrs=artifact,
                client=self.client,
                aliases=[alias.alias for alias in node.aliases],
            )
            for node in nodes
            if (
                (collection := node.artifact_collection)
                and (project := collection.project)
                and (artifact := node.artifact)
            )
        ]
