"""Public API: registries search."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import PositiveInt, ValidationError
from typing_extensions import override
from wandb_gql import gql

from wandb._analytics import tracked
from wandb.apis.paginator import RelayPaginator, SizedRelayPaginator

from ._utils import ensure_registry_prefix_on_names

if TYPE_CHECKING:
    from wandb_graphql.language.ast import Document

    from wandb.apis.public import ArtifactCollection, RetryingClient
    from wandb.sdk.artifacts._generated import (
        ArtifactMembershipFragment,
        RegistryCollectionFragment,
        RegistryFragment,
    )
    from wandb.sdk.artifacts._models.pagination import (
        ArtifactMembershipConnection,
        RegistryCollectionConnection,
        RegistryConnection,
    )
    from wandb.sdk.artifacts.artifact import Artifact

    from .registry import Registry


class Registries(RelayPaginator["RegistryFragment", "Registry"]):
    """A lazy iterator of `Registry` objects."""

    QUERY: ClassVar[Document | None] = None  # type: ignore[misc]
    last_response: RegistryConnection | None

    def __init__(
        self,
        client: RetryingClient,
        organization: str,
        filter: dict[str, Any] | None = None,
        per_page: PositiveInt = 100,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import FETCH_REGISTRIES_GQL

            type(self).QUERY = gql(FETCH_REGISTRIES_GQL)

        self.organization = organization
        self.filter = ensure_registry_prefix_on_names(filter or {})

        variables = {"organization": organization, "filters": json.dumps(self.filter)}
        super().__init__(client, variables=variables, per_page=per_page)

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    @tracked
    def collections(
        self, filter: dict[str, Any] | None = None, per_page: PositiveInt = 100
    ) -> Collections:
        return Collections(
            client=self.client,
            organization=self.organization,
            registry_filter=self.filter,
            collection_filter=filter,
            per_page=per_page,
        )

    @tracked
    def versions(
        self, filter: dict[str, Any] | None = None, per_page: PositiveInt = 100
    ) -> Versions:
        return Versions(
            client=self.client,
            organization=self.organization,
            registry_filter=self.filter,
            collection_filter=None,
            artifact_filter=filter,
            per_page=per_page,
        )

    @property
    def length(self):
        if self.last_response is None:
            return None
        return len(self.last_response.edges)

    @override
    def _update_response(self) -> None:
        from wandb.sdk.artifacts._generated import FetchRegistries
        from wandb.sdk.artifacts._models.pagination import RegistryConnection

        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = FetchRegistries.model_validate(data)
        if not ((org := result.organization) and (org_entity := org.org_entity)):
            raise ValueError(
                f"Organization {self.organization!r} not found. Please verify the organization name is correct."
            )

        try:
            conn = org_entity.projects
            self.last_response = RegistryConnection.model_validate(conn)
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def _convert(self, node: RegistryFragment) -> Registry:
        from wandb.sdk.artifacts._validators import remove_registry_prefix

        from .registry import Registry

        return Registry(
            client=self.client,
            organization=self.organization,
            entity=node.entity.name,
            name=remove_registry_prefix(node.name),
            attrs=node,
        )


class Collections(
    SizedRelayPaginator["RegistryCollectionFragment", "ArtifactCollection"]
):
    """An lazy iterator of `ArtifactCollection` objects in a Registry."""

    QUERY: ClassVar[Document | None] = None  # type: ignore[misc]
    last_response: RegistryCollectionConnection | None

    def __init__(
        self,
        client: RetryingClient,
        organization: str,
        registry_filter: dict[str, Any] | None = None,
        collection_filter: dict[str, Any] | None = None,
        per_page: PositiveInt = 100,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import REGISTRY_COLLECTIONS_GQL

            type(self).QUERY = gql(REGISTRY_COLLECTIONS_GQL)

        self.client = client
        self.organization = organization
        self.registry_filter = registry_filter
        self.collection_filter = collection_filter or {}

        variables = {
            "registryFilter": json.dumps(f) if (f := registry_filter) else None,
            "collectionFilter": json.dumps(f) if (f := collection_filter) else None,
            "organization": organization,
            "perPage": per_page,
        }
        super().__init__(client, variables=variables, per_page=per_page)

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    @tracked
    def versions(
        self, filter: dict[str, Any] | None = None, per_page: PositiveInt = 100
    ) -> Versions:
        return Versions(
            client=self.client,
            organization=self.organization,
            registry_filter=self.registry_filter,
            collection_filter=self.collection_filter,
            artifact_filter=filter,
            per_page=per_page,
        )

    @override
    def _update_response(self) -> None:
        from wandb.sdk.artifacts._generated import RegistryCollections
        from wandb.sdk.artifacts._models.pagination import RegistryCollectionConnection

        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = RegistryCollections.model_validate(data)
        if not ((org := result.organization) and (org_entity := org.org_entity)):
            raise ValueError(
                f"Organization {self.organization!r} not found. Please verify the organization name is correct."
            )

        try:
            conn = org_entity.artifact_collections
            self.last_response = RegistryCollectionConnection.model_validate(conn)
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def _convert(self, node: RegistryCollectionFragment) -> ArtifactCollection | None:
        from wandb._pydantic import gql_typename
        from wandb.apis.public import ArtifactCollection
        from wandb.sdk.artifacts._generated import ArtifactSequenceTypeFields

        if not (
            # We don't _expect_ any registry collections to be
            # ArtifactSequences, but defensively filter them out anyway.
            node.project
            and (node.typename__ != gql_typename(ArtifactSequenceTypeFields))
        ):
            return None
        return ArtifactCollection(
            client=self.client,
            entity=node.project.entity.name,
            project=node.project.name,
            name=node.name,
            type=node.type.name,
            organization=self.organization,
            attrs=node,
        )


class Versions(RelayPaginator["ArtifactMembershipFragment", "Artifact"]):
    """An lazy iterator of `Artifact` objects in a Registry."""

    QUERY: Document  # Must be set per-instance
    last_response: ArtifactMembershipConnection | None

    def __init__(
        self,
        client: RetryingClient,
        organization: str,
        registry_filter: dict[str, Any] | None = None,
        collection_filter: dict[str, Any] | None = None,
        artifact_filter: dict[str, Any] | None = None,
        per_page: PositiveInt = 100,
    ):
        from wandb.sdk.artifacts._generated import REGISTRY_VERSIONS_GQL

        self.QUERY = gql(REGISTRY_VERSIONS_GQL)

        self.client = client
        self.organization = organization
        self.registry_filter = registry_filter
        self.collection_filter = collection_filter
        self.artifact_filter = artifact_filter or {}

        variables = {
            "registryFilter": json.dumps(f) if (f := registry_filter) else None,
            "collectionFilter": json.dumps(f) if (f := collection_filter) else None,
            "artifactFilter": json.dumps(f) if (f := artifact_filter) else None,
            "organization": organization,
        }
        super().__init__(client, variables=variables, per_page=per_page)

    @override
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

    @override
    def _update_response(self) -> None:
        from wandb.sdk.artifacts._generated import RegistryVersions
        from wandb.sdk.artifacts._models.pagination import ArtifactMembershipConnection

        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = RegistryVersions.model_validate(data)
        if not ((org := result.organization) and (org_entity := org.org_entity)):
            raise ValueError(
                f"Organization {self.organization!r} not found. Please verify the organization name is correct."
            )

        try:
            conn = org_entity.artifact_memberships
            self.last_response = ArtifactMembershipConnection.model_validate(conn)
        except (LookupError, AttributeError, ValidationError) as e:
            raise ValueError("Unexpected response data") from e

    def _convert(self, node: ArtifactMembershipFragment) -> Artifact | None:
        from wandb.sdk.artifacts._validators import FullArtifactPath
        from wandb.sdk.artifacts.artifact import Artifact

        if not (
            (collection := node.artifact_collection)
            and (project := collection.project)
            and node.artifact
            and (version_idx := node.version_index) is not None
        ):
            return None
        return Artifact._from_membership(
            membership=node,
            target=FullArtifactPath(
                prefix=project.entity.name,
                project=project.name,
                name=f"{collection.name}:v{version_idx}",
            ),
            client=self.client,
        )
