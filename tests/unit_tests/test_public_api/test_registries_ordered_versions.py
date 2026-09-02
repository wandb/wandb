from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from pytest import fixture, raises
from wandb._strutils import b64encode_ascii
from wandb.apis.public.registries import _utils
from wandb.apis.public.registries._utils import (
    advanced_search_enabled,
    decode_project_id,
    registry_filter_for,
)
from wandb.apis.public.registries.registries_search import Collections, Registries
from wandb.apis.public.registries.registry import Registry
from wandb.errors import UnsupportedError

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest import LogCaptureFixture
    from pytest_mock import MockerFixture

ORG = "test-org"
REGISTRY_FILTER = {"name": "wandb-registry-test"}


def test_registry_filter_uses_internal_id(mocker: MockerFixture):
    registry = mocker.Mock(spec=Registry)
    registry.full_name = "wandb-registry-test"
    registry.internal_id = b64encode_ascii("ProjectInternalId:42")

    assert registry_filter_for(registry) == {"id": 42}


def test_registry_filter_uses_internal_id_from_collection(mocker: MockerFixture):
    from wandb.apis.public import ArtifactCollection

    collection = mocker.Mock(spec=ArtifactCollection)
    collection.project = "wandb-registry-test"
    collection.project_internal_id = b64encode_ascii("ProjectInternalId:42")

    assert registry_filter_for(collection) == {"id": 42}


def test_decode_project_id_on_valid_internal_id():
    gql_id = b64encode_ascii("ProjectInternalId:933111")

    assert decode_project_id(gql_id) == 933111


def test_decode_project_id_on_invalid_internal_id(wandb_caplog: LogCaptureFixture):
    with wandb_caplog.at_level(logging.WARNING, logger=_utils.__name__):
        assert decode_project_id("not-a-valid-gql-id") is None

    assert "Invalid project ID" in wandb_caplog.text


def test_filter_for_registry_falls_back_to_name_for_invalid_internal_id(
    mocker: MockerFixture, wandb_caplog: LogCaptureFixture
):
    registry = mocker.Mock(spec=Registry)
    registry.full_name = "wandb-registry-test"
    registry.internal_id = "not-a-valid-gql-id"

    with wandb_caplog.at_level(logging.WARNING, logger=_utils.__name__):
        assert registry_filter_for(registry) == {"name": "wandb-registry-test"}

    assert "Invalid project ID" in wandb_caplog.text


def test_registry_filter_falls_back_to_project_name_for_invalid_internal_id(
    mocker: MockerFixture,
    wandb_caplog: LogCaptureFixture,
):
    from wandb.apis.public import ArtifactCollection

    collection = mocker.Mock(spec=ArtifactCollection)
    collection.project = "wandb-registry-test"
    collection.project_internal_id = "not-a-valid-gql-id"

    with wandb_caplog.at_level(logging.WARNING, logger=_utils.__name__):
        assert registry_filter_for(collection) == {"name": "wandb-registry-test"}

    assert "Invalid project ID" in wandb_caplog.text


def test_advanced_search_enabled_returns_false_on_graphql_error(
    service_api: MagicMock,
    wandb_caplog: LogCaptureFixture,
):
    service_api.feature_enabled.return_value = True
    service_api.execute_graphql.side_effect = RuntimeError("network down")

    with wandb_caplog.at_level(logging.WARNING, logger=_utils.__name__):
        assert advanced_search_enabled(service_api, ORG) is False

    assert "Failed to fetch advanced registry features" in wandb_caplog.text


def test_registry_filter_falls_back_to_name_without_internal_id(
    mocker: MockerFixture,
):
    registry = mocker.Mock(spec=Registry)
    registry.full_name = "wandb-registry-order-test-reg-0"
    registry.internal_id = None

    assert registry_filter_for(registry) == {"name": "wandb-registry-order-test-reg-0"}


@fixture
def service_api(mocker: MockerFixture) -> MagicMock:
    from wandb.apis.public.service_api import ServiceApi

    mock = mocker.Mock(spec=ServiceApi)
    mock.feature_enabled.return_value = True
    return mock


def test_registries_versions_with_order_rejects_start(service_api):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order="-updated_at",
    )

    with raises(
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

    with raises(
        ValueError, match="is not supported when querying collections from registries"
    ):
        registries.collections(start="cursor")


def test_registries_collections_with_registry_order_supports_versions_chain(
    service_api,
):
    """Check interface chainability without fetching results."""
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

    with raises(UnsupportedError, match="cursor"):
        _ = collections.cursor
    with raises(UnsupportedError, match="cursor"):
        _ = versions.cursor
    with raises(UnsupportedError, match="length"):
        _ = collections.length
    with raises(TypeError, match="len"):
        len(collections)
    with raises(UnsupportedError, match="__getitem__"):
        _ = collections[0]
    with raises(UnsupportedError, match="__getitem__"):
        _ = versions[:1]


def test_registries_collections_versions_with_registry_order_rejects_start(service_api):
    registries = Registries(
        service_api=service_api,
        organization=ORG,
        filter=REGISTRY_FILTER,
        order="-updated_at",
    )

    with raises(
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

    with raises(
        ValueError, match="is not supported when querying versions from collections"
    ):
        collections.versions(start="cursor")
