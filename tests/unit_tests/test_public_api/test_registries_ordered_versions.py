from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

import pytest
from wandb._strutils import b64encode_ascii
from wandb.apis.public.registries import _utils
from wandb.apis.public.registries._utils import (
    _project_id_from_gql_id,
    advanced_search_enabled,
    filter_for_registry,
    registry_filter_for_collection,
)
from wandb.apis.public.registries.registries_search import Collections, Registries
from wandb.apis.public.registries.registry import Registry
from wandb.errors import UnsupportedError

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

ORG = "test-org"
REGISTRY_FILTER = {"name": "wandb-registry-test"}


def test_filter_for_registry_pins_internal_id(mocker):
    registry = mocker.Mock(spec=Registry)
    registry.full_name = "wandb-registry-test"
    registry.internal_id = b64encode_ascii("ProjectInternalId:42")

    assert filter_for_registry(registry) == {"id": 42}


def test_registry_filter_for_collection_pins_internal_id(mocker):
    from wandb.apis.public import ArtifactCollection

    collection = mocker.Mock(spec=ArtifactCollection)
    collection.project = "wandb-registry-test"
    collection.project_internal_id = b64encode_ascii("ProjectInternalId:42")

    assert registry_filter_for_collection(collection) == {"id": 42}


def test_project_id_from_gql_id_decodes_project_internal_id():
    gql_id = b64encode_ascii("ProjectInternalId:933111")

    assert _project_id_from_gql_id(gql_id) == 933111


def test_project_id_from_gql_id_returns_none_for_invalid_id(wandb_caplog):
    with wandb_caplog.at_level(logging.WARNING, logger=_utils.__name__):
        assert _project_id_from_gql_id("not-a-valid-gql-id") is None

    assert "Invalid project ID" in wandb_caplog.text


def test_filter_for_registry_falls_back_to_name_for_invalid_internal_id(
    mocker, wandb_caplog
):
    registry = mocker.Mock(spec=Registry)
    registry.full_name = "wandb-registry-test"
    registry.internal_id = "not-a-valid-gql-id"

    with wandb_caplog.at_level(logging.WARNING, logger=_utils.__name__):
        assert filter_for_registry(registry) == {
            "name": "wandb-registry-test",
        }

    assert "Invalid project ID" in wandb_caplog.text


def test_registry_filter_for_collection_falls_back_to_name_for_invalid_internal_id(
    mocker, wandb_caplog
):
    from wandb.apis.public import ArtifactCollection

    collection = mocker.Mock(spec=ArtifactCollection)
    collection.project = "wandb-registry-test"
    collection.project_internal_id = "not-a-valid-gql-id"

    with wandb_caplog.at_level(logging.WARNING, logger=_utils.__name__):
        assert registry_filter_for_collection(collection) == {
            "name": "wandb-registry-test",
        }

    assert "Invalid project ID" in wandb_caplog.text


def test_advanced_search_enabled_returns_false_on_graphql_error(
    service_api, wandb_caplog
):
    service_api.feature_enabled.return_value = True
    service_api.execute_graphql.side_effect = RuntimeError("network down")

    with wandb_caplog.at_level(logging.WARNING, logger=_utils.__name__):
        assert advanced_search_enabled(service_api, ORG) is False

    assert "Failed to fetch advanced registry features" in wandb_caplog.text


def test_filter_for_registry_falls_back_to_name_without_internal_id(mocker):
    registry = mocker.Mock(spec=Registry)
    registry.full_name = "wandb-registry-order-test-reg-0"
    registry.internal_id = None

    assert filter_for_registry(registry) == {
        "name": "wandb-registry-order-test-reg-0",
    }


@pytest.fixture
def service_api(mocker: MockerFixture) -> MagicMock:
    from wandb.apis.public.service_api import ServiceApi

    mock = mocker.Mock(spec=ServiceApi)
    mock.feature_enabled.return_value = True
    return mock


@pytest.fixture
def registry(service_api: MagicMock) -> Registry:
    registry = Registry(service_api, ORG, entity="entity", name="test")
    registry._current = registry._current.model_copy(
        update={"internal_id": b64encode_ascii("ProjectInternalId:42")}
    )
    return registry


def test_registry_collections_uses_basic_id_filter(
    service_api: MagicMock,
    registry: Registry,
):
    collections = registry.collections()

    assert json.loads(collections.variables["registryFilter"]) == {"id": 42}
    service_api.feature_enabled.assert_not_called()
    service_api.execute_graphql.assert_not_called()


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
    registry,
    mocker,
):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order="-updated_at",
    )
    registries.objects = [registry]
    registries.last_response = mocker.Mock(has_next=False)
    load_collection_page = mocker.patch.object(
        Collections,
        "_load_page",
        autospec=True,
        return_value=False,
    )

    collections = registries.collections()

    assert isinstance(collections, Iterable)
    assert isinstance(registries.collections(), Iterable)

    assert isinstance(registries.versions(), Iterable)
    assert isinstance(collections.versions(), Iterable)
    assert isinstance(registries.collections().versions(), Iterable)

    assert list(collections) == []
    child = load_collection_page.call_args.args[0]
    assert json.loads(child.variables["registryFilter"]) == {"id": 42}
    service_api.feature_enabled.assert_not_called()


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
