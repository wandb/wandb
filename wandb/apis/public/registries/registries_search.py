"""Public API: registries search."""

from __future__ import annotations

from collections.abc import Iterator
from itertools import chain
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Protocol, TypeAlias, TypeVar

from pydantic import AfterValidator, PlainSerializer, PositiveInt, ValidationError
from pydantic.alias_generators import to_camel
from typing_extensions import Never, override

from wandb._analytics import tracked
from wandb._filters import FilterArg
from wandb._pydantic import GQLInput, to_json
from wandb.apis.paginator import Paginator, RelayPaginator, SizedRelayPaginator
from wandb.errors import UnsupportedError

from ._utils import (
    OrderArg,
    prepare_collection_filter,
    prepare_registry_filter,
    prepare_version_filter,
)

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
_RegistryFilter: TypeAlias = Annotated[
    dict[str, Any],
    AfterValidator(
        FilterArg(allowed=("name", "description", "created_at", "updated_at"))
    ),
    AfterValidator(prepare_registry_filter),
    PlainSerializer(to_json),
]
_CollectionFilter: TypeAlias = Annotated[
    dict[str, Any],
    AfterValidator(
        FilterArg(allowed=("name", "tag", "description", "created_at", "updated_at"))
    ),
    AfterValidator(prepare_collection_filter),
    PlainSerializer(to_json),
]
_VersionFilter: TypeAlias = Annotated[
    dict[str, Any],
    AfterValidator(
        FilterArg(allowed=("tag", "alias", "created_at", "updated_at", "metadata"))
    ),
    AfterValidator(prepare_version_filter),
    PlainSerializer(to_json),
]

# Type annotations for `order` arguments.
_RegistryOrder: TypeAlias = Annotated[
    str,
    AfterValidator(OrderArg(allowed=("name", "created_at", "updated_at"))),
]
_CollectionOrder: TypeAlias = Annotated[
    str,
    AfterValidator(OrderArg(allowed=("name", "created_at", "updated_at"))),
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
class _RegistriesVars(GQLInput, alias_generator=to_camel):
    """Validated GraphQL variables for a `Registries` paginator."""

    organization: str

    filters: _RegistryFilter | None = None
    order: _RegistryOrder | None = None
    per_page: PositiveInt = 100


class _CollectionsVars(GQLInput, alias_generator=to_camel):
    """Validated GraphQL variables for a `Collections` paginator."""

    organization: str

    registry_filter: _RegistryFilter | None = None
    collection_filter: _CollectionFilter | None = None
    order: _CollectionOrder | None = None
    per_page: PositiveInt = 100


class _VersionsVars(GQLInput, alias_generator=to_camel):
    """Validated GraphQL variables for a `Versions` paginator."""

    organization: str

    registry_filter: _RegistryFilter | None = None
    collection_filter: _CollectionFilter | None = None
    artifact_filter: _VersionFilter | None = None
    per_page: PositiveInt = 100


class VersionsIterator(Protocol):
    """Public surface of a lazy iterator over registry artifact versions.

    Satisfied by both ``Versions`` and the ordered-chained flattener, so callers get
    one return type regardless of whether the query was ordered.
    """

    def __iter__(self) -> Iterator[Artifact]: ...
    def __next__(self) -> Artifact: ...


class CollectionsIterator(Protocol):
    """Public surface of a lazy iterator over registry collections, chainable to versions.

    Satisfied by both ``Collections`` and the ordered-chained flattener.
    """

    def __iter__(self) -> Iterator[ArtifactCollection]: ...
    def __next__(self) -> ArtifactCollection: ...
    def versions(
        self,
        filter: dict[str, Any] | None = ...,
        per_page: PositiveInt = ...,
        start: str | None = ...,
    ) -> VersionsIterator: ...


class Registries(RelayPaginator["RegistryFragment", "Registry"]):
    """A lazy iterator of `Registry` objects."""

    QUERY: ClassVar[str | None] = None
    last_response: RegistryConnection | None

    def __init__(
        self,
        service_api: ServiceApi,
        organization: str,
        filter: _RegistryFilter | None = None,
        order: _RegistryOrder | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ):

        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import FETCH_REGISTRIES_GQL

            type(self).QUERY = FETCH_REGISTRIES_GQL

        vars_ = _RegistriesVars(
            organization=organization,
            filters=filter,
            order=order,
            per_page=per_page,
        )

        self.organization = vars_.organization
        self.filter = vars_.filters
        self.order = vars_.order

        super().__init__(
            service_api,
            variables=vars_.model_dump(),
            per_page=vars_.per_page,
            start=start,
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
        filter: _CollectionFilter | None = None,
        order: _CollectionOrder | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ) -> CollectionsIterator:
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
                f"fetched with order={registry_order!r}. Remove either 'order' from the "
                "registries query or 'start' from the collections query."
            )
        if registry_order is not None:
            return _OrderedCollections(
                self._service_api,
                self.organization,
                (
                    Collections(
                        service_api=self._service_api,
                        organization=self.organization,
                        registry_filter={"name": reg.full_name},
                        collection_filter=filter,
                        order=order,
                        per_page=per_page,
                    )
                    for reg in self
                ),
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
        filter: _VersionFilter | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ) -> VersionsIterator:
        """Returns the artifact versions belonging to these registries.

        Args:
            filter: Optional mapping of filters to apply to the artifact versions query.
            per_page: The number of results to fetch per page.
                Usually there is no reason to change this.
            start: Pagination cursor for resuming a past query, captured
                from a previous paginator's `.cursor` attribute.
                Not supported when ``registries()`` was called with ``order=``.
        """
        if (order := self.order) and start:
            msg = (
                f"{start=} is not supported when querying versions from registries "
                f"fetched with {order=}. Remove either 'order' from the registries "
                "query or 'start' from the versions query."
            )
            raise ValueError(msg)

        if order and not start:
            return _ChainedPaginators(
                Versions(
                    service_api=self._service_api,
                    organization=self.organization,
                    registry_filter={"name": reg.full_name},
                    artifact_filter=filter,
                    per_page=per_page,
                )
                for reg in self
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

        result = self._execute_query(parse=FetchRegistries.model_validate_json)
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
        registry_filter: _RegistryFilter | None = None,
        collection_filter: _CollectionFilter | None = None,
        order: _CollectionOrder | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ):

        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import REGISTRY_COLLECTIONS_GQL

            type(self).QUERY = REGISTRY_COLLECTIONS_GQL

        vars_ = _CollectionsVars(
            organization=organization,
            registry_filter=registry_filter,
            collection_filter=collection_filter,
            order=order,
            per_page=per_page,
        )

        self.organization = vars_.organization
        self.registry_filter = vars_.registry_filter
        self.collection_filter = vars_.collection_filter
        self.order = vars_.order

        super().__init__(
            service_api,
            variables=vars_.model_dump(),
            per_page=vars_.per_page,
            start=start,
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
        filter: _VersionFilter | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ) -> VersionsIterator:
        """Returns the artifact versions belonging to these collections.

        Args:
            filter: Optional mapping of filters to apply to the artifact versions query.
            per_page: The number of results to fetch per page.
                Usually there is no reason to change this.
            start: Pagination cursor for resuming a past query, captured
                from a previous paginator's `.cursor` attribute.
                Not supported when ``collections()`` was called with ``order=``.
        """
        if (order := self.order) and start:
            msg = (
                f"{start=} is not supported when querying versions from collections "
                f"fetched with {order=}. Remove either 'order' from the collections "
                "query or 'start' from the versions query."
            )
            raise ValueError(msg)

        if order and not start:
            return _ChainedPaginators(
                Versions(
                    service_api=self._service_api,
                    organization=self.organization,
                    artifact_filter=filter,
                    per_page=per_page,
                    registry_filter={"name": coll.project},
                    collection_filter={"name": coll.name},
                )
                for coll in self
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

        result = self._execute_query(parse=RegistryCollections.model_validate_json)
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
        registry_filter: _RegistryFilter | None = None,
        collection_filter: _CollectionFilter | None = None,
        artifact_filter: _VersionFilter | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import REGISTRY_VERSIONS_GQL

            type(self).QUERY = REGISTRY_VERSIONS_GQL

        vars_ = _VersionsVars(
            organization=organization,
            registry_filter=registry_filter,
            collection_filter=collection_filter,
            artifact_filter=artifact_filter,
            per_page=per_page,
        )

        self.organization = vars_.organization
        self.registry_filter = vars_.registry_filter
        self.collection_filter = vars_.collection_filter
        self.artifact_filter = vars_.artifact_filter

        super().__init__(
            service_api,
            variables=vars_.model_dump(),
            per_page=vars_.per_page,
            start=start,
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

        result = self._execute_query(parse=RegistryVersions.model_validate_json)
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


_T = TypeVar("_T")


class _ChainedPaginators(Iterator[_T]):
    """A lazy iterator that flattens ordered child paginators into a single iterator.

    Backs ordered registry queries, which run one child query per (ordered) parent
    registry or collection and maintains the parents' order.
    """

    def __init__(self, children: Iterator[Paginator[_T]]):
        self._items: Iterator[_T] = chain.from_iterable(children)

    def __next__(self) -> _T:
        return next(self._items)

    @property
    def cursor(self) -> Never:
        msg = "`cursor` is not supported for ordered chained registry queries."
        raise UnsupportedError(msg)

    @property
    def length(self) -> Never:
        msg = "`length` is not supported for ordered chained registry queries."
        raise UnsupportedError(msg)

    def __len__(self) -> Never:
        msg = "`__len__` is not supported for ordered chained registry queries."
        raise TypeError(msg)

    def __getitem__(self, index: int | slice) -> Never:
        msg = "`__getitem__` is not supported for ordered chained registry queries."
        raise UnsupportedError(msg)


class _OrderedCollections(_ChainedPaginators["ArtifactCollection"]):
    """Ordered collections chained across registries, chainable to their versions."""

    def __init__(
        self,
        service_api: ServiceApi,
        organization: str,
        children: Iterator[Paginator[ArtifactCollection]],
    ):
        super().__init__(children)
        self._service_api = service_api
        self.organization = organization

    def versions(
        self,
        filter: dict[str, Any] | None = None,
        per_page: PositiveInt = 100,
        start: str | None = None,
    ) -> VersionsIterator:
        if start is not None:
            msg = (
                f"{start=} is not supported when querying versions from registries "
                "fetched with an order. Remove either 'order' from the registries "
                "query or 'start' from the versions query."
            )
            raise ValueError(msg)

        return _ChainedPaginators(
            Versions(
                service_api=self._service_api,
                organization=self.organization,
                registry_filter={"name": col.project},
                collection_filter={"name": col.name},
                artifact_filter=filter,
                per_page=per_page,
            )
            for col in self
        )
