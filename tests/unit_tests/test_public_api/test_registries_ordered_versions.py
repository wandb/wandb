from __future__ import annotations

from collections.abc import Iterable

import pytest
from wandb.apis.public.registries.registries_search import Collections, Registries
from wandb.errors import UnsupportedError

ORG = "test-org"
REGISTRY_FILTER = {"name": "wandb-registry-test"}


@pytest.fixture
def service_api(mocker):
    from wandb.apis.public.service_api import ServiceApi

    return mocker.Mock(spec=ServiceApi)


def test_registries_versions_with_order_rejects_start(service_api):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order="-updated_at",
    )

    with pytest.raises(
        ValueError, match="is not supported when querying versions from registries"
    ):
        registries.versions(start="cursor")


def test_registries_collections_with_order_rejects_start(service_api):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order="name",
    )

    with pytest.raises(
        ValueError, match="is not supported when querying collections from registries"
    ):
        registries.collections(start="cursor")


def test_registries_collections_with_registry_order_supports_versions_chain(
    service_api,
):
    """Test that we can chain versions after collections when querying registries with an order.

    Note that this deliberately only checks for iterability and chainability, not actual results.
    """
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order="-updated_at",
    )

    collections = registries.collections()

    assert isinstance(collections, Iterable)
    assert isinstance(registries.collections(), Iterable)

    assert isinstance(registries.versions(), Iterable)
    assert isinstance(collections.versions(), Iterable)
    assert isinstance(registries.collections().versions(), Iterable)


def test_ordered_chained_queries_reject_cursor_and_length(service_api):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order="-updated_at",
    )

    collections = registries.collections()
    versions = registries.versions()

    with pytest.raises(UnsupportedError, match="cursor"):
        _ = collections.cursor
    with pytest.raises(UnsupportedError, match="cursor"):
        _ = versions.cursor
    with pytest.raises(UnsupportedError, match="length"):
        _ = collections.length
    with pytest.raises(TypeError, match="len"):
        len(collections)
    with pytest.raises(UnsupportedError, match="__getitem__"):
        _ = collections[0]
    with pytest.raises(UnsupportedError, match="__getitem__"):
        _ = versions[:1]


def test_registries_collections_versions_with_registry_order_rejects_start(service_api):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order="-updated_at",
    )

    with pytest.raises(
        ValueError, match="is not supported when querying versions from registries"
    ):
        registries.collections().versions(start="cursor")


def test_collections_versions_with_order_rejects_start(service_api):
    collections = Collections(
        service_api=service_api,
        organization=ORG,
        registry_filter=REGISTRY_FILTER,
        collection_filter={"name": {"$contains": "model"}},
        order="-updated_at",
    )

    with pytest.raises(
        ValueError, match="is not supported when querying versions from collections"
    ):
        collections.versions(start="cursor")
