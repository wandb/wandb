from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from wandb._strutils import b64encode_ascii
from wandb.apis.public.registries._utils import (
    fetch_advanced_search_enabled,
    registry_filter_for_collection,
    registry_filter_for_registry,
    registry_project_id_filter_key,
)
from wandb.apis.public.registries.registries_search import (
    Collections,
    Registries,
    Versions,
)

ORG = "test-org"
REGISTRY_FILTER = {"name": "wandb-registry-test"}


@pytest.fixture(autouse=True)
def clear_registry_filter_caches():
    fetch_advanced_search_enabled.cache_clear()
    registry_project_id_filter_key.cache_clear()
    yield
    fetch_advanced_search_enabled.cache_clear()
    registry_project_id_filter_key.cache_clear()


def _mock_advanced_search(service_api, *, enabled: bool) -> None:
    service_api.execute_graphql.return_value = {
        "organization": {
            "advancedRegistryFeatures": {"advancedSearch": enabled},
        }
    }


@pytest.mark.parametrize(
    ("enabled", "key"),
    [(True, "id"), (False, "project_id")],
    ids=["clickhouse", "non_clickhouse"],
)
def test_registry_filter_for_registry_uses_project_id_key(
    service_api, enabled, key
):
    _mock_advanced_search(service_api, enabled=enabled)
    registry = MagicMock()
    registry.full_name = "wandb-registry-test"
    registry.id = b64encode_ascii("Project:42")

    assert registry_filter_for_registry(
        registry, service_api=service_api, organization=ORG
    ) == {
        "name": "wandb-registry-test",
        key: 42,
    }


def test_registry_filter_for_collection_uses_project_id_key(service_api):
    _mock_advanced_search(service_api, enabled=True)
    collection = MagicMock()
    collection.project = "wandb-registry-test"
    collection.project_gql_id = b64encode_ascii("Project:42")

    assert registry_filter_for_collection(
        collection, service_api=service_api, organization=ORG
    ) == {
        "name": "wandb-registry-test",
        "id": 42,
    }


@pytest.fixture
def service_api(mocker):
    from wandb.apis.public.service_api import ServiceApi

    return mocker.Mock(spec=ServiceApi)


@pytest.mark.parametrize(
    "order",
    [None, "-updated_at"],
    ids=["without_order", "with_order"],
)
def test_registries_versions(service_api, order):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order=order,
    )

    result = registries.versions()

    if order is None:
        assert isinstance(result, Versions)
    else:
        assert isinstance(result, Iterator)
        assert not isinstance(result, Versions)


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


@pytest.mark.parametrize(
    ("registry_order", "collection_order"),
    [
        (None, "-updated_at"),
        ("name", None),
        ("name", "-updated_at"),
    ],
    ids=["without_registry_order", "with_registry_order", "with_both_orders"],
)
def test_registries_collections(service_api, registry_order, collection_order):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order=registry_order,
    )

    result = registries.collections(order=collection_order)

    if registry_order is None:
        assert isinstance(result, Collections)
        assert result.order == collection_order
    else:
        assert isinstance(result, Iterator)
        assert not isinstance(result, Collections)


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


@pytest.mark.parametrize(
    "kwargs",
    [
        {"collection_filter": {"name": "my-collection"}},
        {
            "collection_filter": {"name": {"$contains": "model"}},
            "order": "-updated_at",
        },
    ],
    ids=["without_order", "with_collection_order"],
)
def test_collections_versions(service_api, kwargs):
    collections = Collections(
        service_api=service_api,
        organization=ORG,
        registry_filter=REGISTRY_FILTER,
        **kwargs,
    )

    result = collections.versions()

    if kwargs.get("order") is None:
        assert isinstance(result, Versions)
    else:
        assert isinstance(result, Iterator)
        assert not isinstance(result, Versions)


def test_registries_collections_versions_with_registry_and_collection_order(
    service_api,
):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order="-updated_at",
    )

    result = (
        version
        for collection in registries.collections(order="name")
        for version in Collections(
            service_api=service_api,
            organization=ORG,
            registry_filter={"name": collection.project},
            collection_filter={"name": collection.name},
        ).versions()
    )

    assert isinstance(result, Iterator)
    assert not isinstance(result, Versions)


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
