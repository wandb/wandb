from __future__ import annotations

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
    ("order", "expected_registry_order"),
    [
        (None, None),
        ("-updated_at", "-updated_at"),
    ],
    ids=["without_order", "with_order"],
)
def test_registries_versions(service_api, order, expected_registry_order):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order=order,
    )

    result = registries.versions()

    assert isinstance(result, Versions)
    assert result.registry_order == expected_registry_order
    if order is not None:
        assert result.registries_per_page == registries.per_page


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
    ("kwargs", "expected"),
    [
        (
            {"collection_filter": {"name": "my-collection"}},
            {"collection_order": None, "registry_order": None},
        ),
        (
            {
                "collection_filter": {"name": {"$contains": "model"}},
                "order": "-updated_at",
            },
            {"collection_order": "-updated_at", "registry_order": None},
        ),
        (
            {
                "order": "name",
                "registry_order": "-updated_at",
                "registries_per_page": 50,
            },
            {
                "collection_order": "name",
                "registry_order": "-updated_at",
                "registries_per_page": 50,
            },
        ),
    ],
    ids=["without_order", "with_collection_order", "with_registry_and_collection_order"],
)
def test_collections_versions(service_api, kwargs, expected):
    collections = Collections(
        service_api=service_api,
        organization=ORG,
        registry_filter=REGISTRY_FILTER,
        **kwargs,
    )

    result = collections.versions()

    assert isinstance(result, Versions)
    assert result.collection_order == expected["collection_order"]
    assert result.registry_order == expected["registry_order"]
    if registries_per_page := expected.get("registries_per_page"):
        assert result.registries_per_page == registries_per_page
    elif expected["collection_order"] is not None:
        assert result.collections_per_page == collections.per_page


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
