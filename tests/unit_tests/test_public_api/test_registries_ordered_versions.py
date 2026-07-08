from __future__ import annotations

from collections.abc import Iterator

import pytest
from wandb.apis.public.registries.registries_search import (
    Collections,
    Registries,
    Versions,
)

ORG = "test-org"
REGISTRY_FILTER = {"name": "wandb-registry-test"}


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


def test_registries_collections_passes_registry_order(service_api):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order="name",
    )

    result = registries.collections(order="-updated_at")

    assert isinstance(result, Collections)
    assert result.registry_order == "name"
    assert result.order == "-updated_at"
    assert result.registries_per_page == registries.per_page


@pytest.mark.parametrize(
    "kwargs",
    [
        {"collection_filter": {"name": "my-collection"}},
        {
            "collection_filter": {"name": {"$contains": "model"}},
            "order": "-updated_at",
        },
        {
            "order": "name",
            "registry_order": "-updated_at",
            "registries_per_page": 50,
        },
    ],
    ids=[
        "without_order",
        "with_collection_order",
        "with_registry_and_collection_order",
    ],
)
def test_collections_versions(service_api, kwargs):
    collections = Collections(
        service_api=service_api,
        organization=ORG,
        registry_filter=REGISTRY_FILTER,
        **kwargs,
    )

    result = collections.versions()

    ordered = (
        kwargs.get("order") is not None or kwargs.get("registry_order") is not None
    )
    if ordered:
        assert isinstance(result, Iterator)
        assert not isinstance(result, Versions)
    else:
        assert isinstance(result, Versions)


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
