from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wandb.apis.public.registries.registries_search import (
    Collections,
    Registries,
    Versions,
)


def test_registries_versions_without_order_returns_versions_paginator():
    service_api = MagicMock()
    registries = Registries(
        service_api=service_api,
        organization="test-org",
        filter={"name": "wandb-registry-test"},
    )

    result = registries.versions(filter={"alias": "latest"})

    assert isinstance(result, Versions)
    assert result.registry_order is None


def test_registries_versions_with_order_configures_ordered_versions():
    service_api = MagicMock()
    registries = Registries(
        service_api=service_api,
        organization="test-org",
        filter={"name": "wandb-registry-test"},
        order="-updated_at",
    )

    result = registries.versions(filter={"metadata.icv_uuid": {"$ne": None}})

    assert isinstance(result, Versions)
    assert result.registry_order == "-updated_at"
    assert result.registries_per_page == registries.per_page


def test_registries_versions_with_order_rejects_start():
    service_api = MagicMock()
    registries = Registries(
        service_api=service_api,
        organization="test-org",
        filter={"name": "wandb-registry-test"},
        order="-updated_at",
    )

    with pytest.raises(ValueError, match="start= is not supported"):
        registries.versions(start="cursor")


def test_registries_collections_passes_registry_order():
    service_api = MagicMock()
    registries = Registries(
        service_api=service_api,
        organization="test-org",
        filter={"name": "wandb-registry-test"},
        order="name",
    )

    result = registries.collections(order="-updated_at")

    assert isinstance(result, Collections)
    assert result.registry_order == "name"
    assert result.order == "-updated_at"
    assert result.registries_per_page == registries.per_page


def test_collections_versions_without_order_returns_versions_paginator():
    service_api = MagicMock()
    collections = Collections(
        service_api=service_api,
        organization="test-org",
        registry_filter={"name": "wandb-registry-test"},
        collection_filter={"name": "my-collection"},
    )

    result = collections.versions(filter={"alias": "latest"})

    assert isinstance(result, Versions)
    assert result.collection_order is None
    assert result.registry_order is None


def test_collections_versions_with_order_configures_ordered_versions():
    service_api = MagicMock()
    collections = Collections(
        service_api=service_api,
        organization="test-org",
        registry_filter={"name": "wandb-registry-test"},
        collection_filter={"name": {"$contains": "model"}},
        order="-updated_at",
    )

    result = collections.versions(filter={"metadata.icv_uuid": {"$ne": None}})

    assert isinstance(result, Versions)
    assert result.collection_order == "-updated_at"
    assert result.collections_per_page == collections.per_page


def test_collections_versions_with_registry_and_collection_order():
    service_api = MagicMock()
    collections = Collections(
        service_api=service_api,
        organization="test-org",
        registry_filter={"name": "wandb-registry-test"},
        order="name",
        registry_order="-updated_at",
        registries_per_page=50,
    )

    result = collections.versions()

    assert result.registry_order == "-updated_at"
    assert result.collection_order == "name"
    assert result.registries_per_page == 50


def test_collections_versions_with_order_rejects_start():
    service_api = MagicMock()
    collections = Collections(
        service_api=service_api,
        organization="test-org",
        registry_filter={"name": "wandb-registry-test"},
        collection_filter={"name": {"$contains": "model"}},
        order="-updated_at",
    )

    with pytest.raises(ValueError, match="start= is not supported"):
        collections.versions(start="cursor")
