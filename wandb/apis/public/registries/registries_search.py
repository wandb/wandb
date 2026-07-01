"""Public API: registries search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, ClassVar, TypeAlias

from pydantic import AfterValidator, PositiveInt, ValidationError
from pydantic.dataclasses import dataclass as pydantic_dataclass
from typing_extensions import override

from wandb._analytics import tracked
from wandb._pydantic import to_json
from wandb.apis.paginator import RelayPaginator, SizedRelayPaginator

from ._utils import OrderValidator, validate_registry_filter

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


# Type annotations for `filter` arguments.
# TODO: Recursively validate allowed filter field names, see e.g. existing mongo filter types in automations.
_RegistryFilter: TypeAlias = Annotated[
    dict[str, Any] | None,
    AfterValidator(validate_registry_filter),
]
_CollectionFilter: TypeAlias = dict[str, Any] | None
_VersionFilter: TypeAlias = dict[str, Any] | None

# Type annotations for `order` arguments.
_RegistryOrder: TypeAlias = Annotated[
    str | None,
    OrderValidator(allowed=("name", "created_at", "updated_at")),
]
_CollectionOrder: TypeAlias = Annotated[
    str | None,
    OrderValidator(allowed=("name", "created_at", "updated_at")),
]


# Note on the validated args classes below:
#
# Ideally, `Registries` itself would just be a pydantic model, but we would
# want to refactor the paginator base types into pydantic models first, which has
# a larger blast radius. This is an intermediate solution that avoids unexpected
# side effects from subclassing a pydantic model from a non-pydantic parent class.
#
# Long term, consider making `Registries` and other paginator types directly into
# pydantic models to automatically validate their arguments at runtime.
#
# Also, using the `@validate_call` decorator does not work at the time of writing,
# since it would require an eager import of `ServiceApi`, causing an import cycle.
@pydantic_dataclass(frozen=True, slots=True)
class _RegistriesVars:
    """Validated arguments for instantiating a `Registries` paginator."""

    organization: str
    filter: _RegistryFilter = None
    order: _RegistryOrder = None
    per_page: PositiveInt = 100
    start: str | None = None


@pydantic_dataclass(frozen=True, slots=True)
class _CollectionsVars:
    """Validated arguments for instantiating a `Collections` paginator."""

    organization: str
    registry_filter: _RegistryFilter = None
    collection_filter: _CollectionFilter = None
    order: _CollectionOrder = None
    per_page: PositiveInt = 100
    start: str | None = None


@pydantic_dataclass(frozen=True, slots=True)
class _VersionsVars:
    """Validated arguments for instantiating a `Versions` paginator."""

    organization: str
    registry_filter: _RegistryFilter = None
    collection_filter: _CollectionFilter = None
    artifact_filter: _VersionFilter = None
    per_page: PositiveInt = 100
    start: str | None = None


class Registries(RelayPaginator["RegistryFragment", "Registry"]):
    """A lazy iterator of `Registry` objects."""

    QUERY: ClassVar[str | None] = None
    last_response: RegistryConnection | None

    def __init__(
        self,
        service_api: ServiceApi,
        organization: str,
        filter: _RegistryFilter = None,
        order: _RegistryOrder = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ):

        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import FETCH_REGISTRIES_GQL

            type(self).QUERY = FETCH_REGISTRIES_GQL

        args = _RegistriesVars(
            organization=organization,
            filter=filter,
            order=order,
            per_page=per_page,
            start=start,
        )

        self.organization = args.organization
        self.filter = args.filter

        variables = {
            "organization": args.organization,
            "filters": to_json(f) if (f := args.filter) else None,
            "order": args.order,
        }
        super().__init__(
            service_api, variables=variables, per_page=args.per_page, start=args.start
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
        """
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
        """
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
        registry_filter: _RegistryFilter = None,
        collection_filter: _CollectionFilter = None,
        order: _CollectionOrder = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ):

        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import REGISTRY_COLLECTIONS_GQL

            type(self).QUERY = REGISTRY_COLLECTIONS_GQL

        args = _CollectionsVars(
            organization=organization,
            registry_filter=registry_filter,
            collection_filter=collection_filter,
            order=order,
            per_page=per_page,
            start=start,
        )

        self.organization = args.organization
        self.registry_filter = args.registry_filter
        self.collection_filter = args.collection_filter

        variables = {
            "registryFilter": to_json(f) if (f := args.registry_filter) else None,
            "collectionFilter": to_json(f) if (f := args.collection_filter) else None,
            "organization": args.organization,
            "order": args.order,
            "perPage": args.per_page,
        }
        super().__init__(
            service_api, variables=variables, per_page=args.per_page, start=args.start
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
        """
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

    QUERY: ClassVar[str | None] = None
    last_response: ArtifactMembershipConnection | None

    def __init__(
        self,
        service_api: ServiceApi,
        organization: str,
        registry_filter: _RegistryFilter = None,
        collection_filter: _CollectionFilter = None,
        artifact_filter: _VersionFilter = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import REGISTRY_VERSIONS_GQL

            type(self).QUERY = REGISTRY_VERSIONS_GQL

        args = _VersionsVars(
            organization=organization,
            registry_filter=registry_filter,
            collection_filter=collection_filter,
            artifact_filter=artifact_filter,
            per_page=per_page,
            start=start,
        )

        self.organization = args.organization
        self.registry_filter = args.registry_filter
        self.collection_filter = args.collection_filter
        self.artifact_filter = args.artifact_filter

        variables = {
            "registryFilter": to_json(f) if (f := args.registry_filter) else None,
            "collectionFilter": to_json(f) if (f := args.collection_filter) else None,
            "artifactFilter": to_json(f) if (f := args.artifact_filter) else None,
            "organization": args.organization,
        }
        super().__init__(
            service_api, variables=variables, per_page=args.per_page, start=args.start
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
