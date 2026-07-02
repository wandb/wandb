from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wandb.apis.public.registries.registries_search import (
    Collections,
    OrderedCollectionVersions,
    Versions,
)


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
    assert not isinstance(result, OrderedCollectionVersions)


def test_collections_versions_with_order_returns_ordered_iterator():
    service_api = MagicMock()
    collections = Collections(
        service_api=service_api,
        organization="test-org",
        registry_filter={"name": "wandb-registry-test"},
        collection_filter={"name": {"$contains": "model"}},
        order="-updated_at",
    )

    result = collections.versions(filter={"metadata.icv_uuid": {"$ne": None}})

    assert isinstance(result, OrderedCollectionVersions)
    assert isinstance(result, Versions)


def test_ordered_collection_versions_rejects_start():
    service_api = MagicMock()

    with pytest.raises(ValueError, match="start= is not supported"):
        OrderedCollectionVersions(
            service_api=service_api,
            organization="test-org",
            registry_filter={"name": "wandb-registry-test"},
            collection_filter={"name": {"$contains": "model"}},
            order="-updated_at",
            artifact_filter=None,
            per_page=100,
            collections_per_page=100,
            start="cursor",
        )
