"""Public API: registries search."""

from __future__ import annotations

import json
from collections.abc import Iterator
from itertools import islice
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, overload

from pydantic import PositiveInt, ValidationError
from typing_extensions import override

from wandb._analytics import tracked
from wandb.apis.paginator import RelayPaginator, SizedRelayPaginator
from wandb.errors import UnsupportedError

from ._utils import ensure_registry_prefix_on_names

if TYPE_CHECKING:
    from wandb.apis.public import ArtifactCollection
    from wandb.apis.public.registries.registry import Registry
    from wandb.apis.public.service_api import ServiceApi
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


class Registries(RelayPaginator["RegistryFragment", "Registry"]):
    """A lazy iterator of `Registry` objects."""

    QUERY: ClassVar[str | None] = None
    last_response: RegistryConnection | None

    def __init__(
        self,
        service_api: ServiceApi,
        organization: str,
        filter: dict[str, Any] | None = None,
        order: str | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import FETCH_REGISTRIES_GQL

            type(self).QUERY = FETCH_REGISTRIES_GQL

        self.organization = organization
        self.filter = ensure_registry_prefix_on_names(filter or {})
        self.order = order
        self._service_api = service_api

        variables = {
            "organization": organization,
            "filters": json.dumps(self.filter),
            "order": order,
        }
        super().__init__(
            service_api, variables=variables, per_page=per_page, start=start
        )

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    @tracked
    def collections(
        self,
        filter: dict[str, Any] | None = None,
        order: str | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ) -> Collections:
        """Returns the collections belonging to these registries.

        Args:
            filter: Optional mapping of filters to apply to the collections query.
            order: Optional string to specify the order of the results.
                If prefixed with '+', sorts ascending (default).
                If prefixed with '-', sorts descending.
            per_page: The number of results to fetch per page.
                Usually there is no reason to change this.
            start: Pagination cursor for resuming a past query, captured
                from a previous paginator's `.cursor` attribute.
                Not supported when ``registries()`` was called with ``order=``.
        """
        if (registry_order := self.order) is not None and start is not None:
            raise ValueError(
                f"{start=} is not supported when querying collections from registries "
                f"fetched with {registry_order=}. Remove either 'order' from the "
                "registries query or 'start' from the collections query."
            )
        if self.order is not None:
            return _ChildCollections(
                parent=self,
                collection_filter=filter,
                order=order,
                per_page=per_page,
            )
        return Collections(
            service_api=self._service_api,
            organization=self.organization,
            registry_filter=self.filter,
            collection_filter=filter,
            order=order,
            per_page=per_page,
            start=start,
        )

    @tracked
    def versions(
        self,
        filter: dict[str, Any] | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ) -> Versions:
        """Returns the artifact versions belonging to these registries.

        Args:
            filter: Optional mapping of filters to apply to the artifact versions query.
            per_page: The number of results to fetch per page.
                Usually there is no reason to change this.
            start: Pagination cursor for resuming a past query, captured
                from a previous paginator's `.cursor` attribute.
                Not supported when ``registries()`` was called with ``order=``.
        """
        if (order := self.order) is not None and start is not None:
            raise ValueError(
                f"{start=} is not supported when querying versions from registries "
                f"fetched with {order=}. Remove either 'order' from the registries "
                "query or 'start' from the versions query."
            )
        if self.order is not None:
            return _ChildVersions(
                parent=self,
                artifact_filter=filter,
                per_page=per_page,
            )
        return Versions(
            service_api=self._service_api,
            organization=self.organization,
            registry_filter=self.filter,
            collection_filter=None,
            artifact_filter=filter,
            per_page=per_page,
            start=start,
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

        data = self._service_api.execute_graphql(self.QUERY, variables=self.variables)
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
        from wandb.apis.public.registries.registry import Registry
        from wandb.sdk.artifacts._validators import remove_registry_prefix

        return Registry(
            service_api=self._service_api,
            organization=self.organization,
            entity=node.entity.name,
            name=remove_registry_prefix(node.name),
            attrs=node,
        )


class Collections(
    SizedRelayPaginator["RegistryCollectionFragment", "ArtifactCollection"]
):
    """An lazy iterator of `ArtifactCollection` objects in a Registry."""

    QUERY: ClassVar[str | None] = None
    last_response: RegistryCollectionConnection | None

    def __init__(
        self,
        service_api: ServiceApi,
        organization: str,
        registry_filter: dict[str, Any] | None = None,
        collection_filter: dict[str, Any] | None = None,
        order: str | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import REGISTRY_COLLECTIONS_GQL

            type(self).QUERY = REGISTRY_COLLECTIONS_GQL

        self.organization = organization
        self.registry_filter = registry_filter or {}
        self.collection_filter = collection_filter or {}
        self.order = order
        self._service_api = service_api

        variables = {
            "registryFilter": json.dumps(f) if (f := registry_filter) else None,
            "collectionFilter": json.dumps(f) if (f := collection_filter) else None,
            "organization": organization,
            "order": order,
            "perPage": per_page,
        }
        super().__init__(
            service_api, variables=variables, per_page=per_page, start=start
        )

    def __next__(self):
        # Implement custom next since its possible to load empty pages because of auth
        self.index += 1
        while len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
        return self.objects[self.index]

    @tracked
    def versions(
        self,
        filter: dict[str, Any] | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ) -> Versions:
        """Returns the artifact versions belonging to these collections.

        Args:
            filter: Optional mapping of filters to apply to the artifact versions query.
            per_page: The number of results to fetch per page.
                Usually there is no reason to change this.
            start: Pagination cursor for resuming a past query, captured
                from a previous paginator's `.cursor` attribute.
                Not supported when ``collections()`` was called with ``order=``.
        """
        if (order := self.order) is not None and start is not None:
            raise ValueError(
                f"{start=} is not supported when querying versions from collections "
                f"fetched with {order=}. Remove either 'order' from the collections "
                "query or 'start' from the versions query."
            )
        if self.order is not None:
            return _ChildVersions(
                parent=self,
                artifact_filter=filter,
                per_page=per_page,
            )
        return Versions(
            service_api=self._service_api,
            organization=self.organization,
            registry_filter=self.registry_filter,
            collection_filter=self.collection_filter,
            artifact_filter=filter,
            per_page=per_page,
            start=start,
        )

    @override
    def _update_response(self) -> None:
        from wandb.sdk.artifacts._generated import RegistryCollections
        from wandb.sdk.artifacts._models.pagination import RegistryCollectionConnection

        data = self._service_api.execute_graphql(self.QUERY, variables=self.variables)
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
            service_api=self._service_api,
            entity=node.project.entity.name,
            project=node.project.name,
            name=node.name,
            type=node.type.name,
            organization=self.organization,
            attrs=node,
        )


class Versions(RelayPaginator["ArtifactMembershipFragment", "Artifact"]):
    """An lazy iterator of `Artifact` objects in a Registry."""

    QUERY: str  # Must be set per-instance
    last_response: ArtifactMembershipConnection | None

    def __init__(
        self,
        service_api: ServiceApi,
        organization: str,
        registry_filter: dict[str, Any] | None = None,
        collection_filter: dict[str, Any] | None = None,
        artifact_filter: dict[str, Any] | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ):
        from wandb.sdk.artifacts._generated import REGISTRY_VERSIONS_GQL

        self.QUERY = REGISTRY_VERSIONS_GQL

        self.organization = organization
        self.registry_filter = registry_filter
        self.collection_filter = collection_filter
        self.artifact_filter = artifact_filter or {}
        self._service_api = service_api

        variables = {
            "registryFilter": json.dumps(f) if (f := registry_filter) else None,
            "collectionFilter": json.dumps(f) if (f := collection_filter) else None,
            "artifactFilter": json.dumps(f) if (f := artifact_filter) else None,
            "organization": organization,
        }
        super().__init__(
            service_api, variables=variables, per_page=per_page, start=start
        )

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

        data = self._service_api.execute_graphql(self.QUERY, variables=self.variables)
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
            service_api=self._service_api,
        )


_ParentT = TypeVar("_ParentT", Registries, Collections)


class _ChildCollections(Collections):
    def __init__(
        self,
        parent: Registries,
        collection_filter: dict[str, Any] | None = None,
        order: str | None = None,
        per_page: PositiveInt = 100,
    ):
        super().__init__(
            service_api=parent._service_api,
            organization=parent.organization,
            registry_filter=parent.filter,
            collection_filter=collection_filter,
            order=order,
            per_page=per_page,
        )
        self._children: Iterator[Collections] | None = (
            Collections(
                service_api=self._service_api,
                organization=self.organization,
                registry_filter={"name": registry.full_name},
                collection_filter=self.collection_filter,
                order=self.order,
                per_page=self.per_page,
            )
            for registry in parent
        )
        self._active_child: Collections | None = None

    @property
    @override
    def more(self) -> bool:
        return self._children is not None or self._active_child is not None

    @property
    @override
    def cursor(self) -> str | None:
        raise UnsupportedError(
            "`cursor` is not supported for ordered chained registry queries. "
            "The result is flattened across multiple child queries, so there is no single cursor."
        )

    @property
    def length(self) -> int | None:
        raise UnsupportedError(
            "`length` is not supported for ordered chained registry queries. "
            "The result is flattened across multiple child queries, so there is no single length."
        )

    @override
    def __len__(self) -> int:
        raise TypeError(
            "`len(...)` is not supported for ordered chained registry queries. "
            "The result is flattened across multiple child queries, so there is no single length."
        )

    @overload
    def __getitem__(self, index: int) -> ArtifactCollection: ...

    @overload
    def __getitem__(self, index: slice) -> list[ArtifactCollection]: ...

    @override
    def __getitem__(
        self, index: int | slice
    ) -> ArtifactCollection | list[ArtifactCollection]:
        raise UnsupportedError(
            "`__getitem__` is not supported for ordered chained registry queries. "
            "The result is flattened across multiple child queries, so indexed access would hide cross-query pagination."
        )

    @tracked
    def versions(
        self,
        filter: dict[str, Any] | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ) -> Versions:
        if start is not None:
            raise ValueError(
                f"{start=} is not supported when querying versions from registries "
                "fetched with an order. Remove either 'order' from the registries "
                "query or 'start' from the versions query."
            )
        return _ChildVersions(
            parent=self,
            artifact_filter=filter,
            per_page=per_page,
        )

    @override
    def _load_page(self) -> bool:
        page: list[ArtifactCollection] = []
        while len(page) < self.per_page:
            if self._active_child is None:
                if self._children is None:
                    break
                try:
                    self._active_child = next(self._children)
                except StopIteration:
                    self._children = None
                    break

            remaining = self.per_page - len(page)
            page.extend(islice(self._active_child, remaining))
            if len(page) < self.per_page:
                self._active_child = None

        self.objects.extend(page)
        return len(page) > 0


class _ChildVersions(Versions, Generic[_ParentT]):
    def __init__(
        self,
        parent: _ParentT,
        artifact_filter: dict[str, Any] | None = None,
        per_page: PositiveInt = 100,
    ):
        super().__init__(
            service_api=parent._service_api,
            organization=parent.organization,
            artifact_filter=artifact_filter,
            per_page=per_page,
        )
        if isinstance(parent, Registries):
            self._children: Iterator[Versions] | None = (
                Versions(
                    service_api=self._service_api,
                    organization=self.organization,
                    registry_filter={"name": registry.full_name},
                    collection_filter=None,
                    artifact_filter=self.artifact_filter,
                    per_page=self.per_page,
                )
                for registry in parent
            )
        else:
            self._children = (
                Versions(
                    service_api=self._service_api,
                    organization=self.organization,
                    registry_filter={"name": collection.project}
                    if collection.project
                    else None,
                    collection_filter={"name": collection.name}
                    if collection.name
                    else None,
                    artifact_filter=self.artifact_filter,
                    per_page=self.per_page,
                )
                for collection in parent
            )
        self._active_child: Versions | None = None

    @property
    @override
    def more(self) -> bool:
        return self._children is not None or self._active_child is not None

    @property
    @override
    def cursor(self) -> str | None:
        raise UnsupportedError(
            "`cursor` is not supported for ordered chained registry queries. "
            "The result is flattened across multiple child queries, so there is no single cursor."
        )

    @property
    @override
    def length(self) -> int | None:
        raise UnsupportedError(
            "`length` is not supported for ordered chained registry queries. "
            "The result is flattened across multiple child queries, so there is no single length."
        )

    def __len__(self) -> int:
        raise TypeError(
            "`len(...)` is not supported for ordered chained registry queries. "
            "The result is flattened across multiple child queries, so there is no single length."
        )

    @overload
    def __getitem__(self, index: int) -> Artifact: ...

    @overload
    def __getitem__(self, index: slice) -> list[Artifact]: ...

    @override
    def __getitem__(self, index: int | slice) -> Artifact | list[Artifact]:
        raise UnsupportedError(
            "`__getitem__` is not supported for ordered chained registry queries. "
            "The result is flattened across multiple child queries, so indexed access would hide cross-query pagination."
        )

    @override
    def _load_page(self) -> bool:
        page: list[Artifact] = []
        while len(page) < self.per_page:
            if self._active_child is None:
                if self._children is None:
                    break
                try:
                    self._active_child = next(self._children)
                except StopIteration:
                    self._children = None
                    break

            remaining = self.per_page - len(page)
            page.extend(islice(self._active_child, remaining))
            if len(page) < self.per_page:
                self._active_child = None

        self.objects.extend(page)
        return len(page) > 0
