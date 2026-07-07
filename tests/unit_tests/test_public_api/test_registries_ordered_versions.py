from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wandb.apis.public.registries.registries_search import Collections, Versions


def test_registry_filter_for_collection_pins_project_id():
    service_api = MagicMock()
    versions = Versions(
        service_api=service_api,
        organization="test-org",
        registry_filter={"name": "wandb-registry-test"},
        collection_order="name",
    )
    collection = MagicMock()
    collection._project_id = "project-id-456"

    assert versions._registry_filter_for_collection(collection) == {
        "name": "wandb-registry-test",
        "id": "project-id-456",
    }


def test_registry_filter_for_collection_without_project_id():
    service_api = MagicMock()
    versions = Versions(
        service_api=service_api,
        organization="test-org",
        registry_filter={"name": "wandb-registry-test"},
        collection_order="name",
    )
    collection = MagicMock()
    collection._project_id = None

    assert versions._registry_filter_for_collection(collection) == {
        "name": "wandb-registry-test",
    }


def test_versions_filter_for_collection_pins_name_and_id():
    service_api = MagicMock()
    versions = Versions(
        service_api=service_api,
        organization="test-org",
        registry_filter={"name": "wandb-registry-test"},
        collection_filter={"name": {"$contains": "model"}},
        collection_order="name",
    )
    collection = MagicMock()
    collection.name = "my-collection"
    collection.id = "collection-id-123"

    assert versions._versions_filter_for_collection(collection) == {
        "name": "my-collection",
        "id": "collection-id-123",
    }


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
