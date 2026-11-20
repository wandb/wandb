"""Tests for the order and failure handling of `Registry.save()`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pytest import fixture, raises
from wandb._strutils import b64encode_ascii
from wandb.apis.public.registries.registry import Registry
from wandb.sdk.artifacts._generated import (
    RENAME_REGISTRY_GQL,
    UPSERT_REGISTRY_GQL,
    RegistryFragment,
    RenameRegistry,
    UpsertRegistry,
)
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

ORG = "test-org"
ORG_ENTITY = "test-org-entity"
PREFIX = "wandb-registry-"


class FakeRegistryServer:
    """Serves the registry mutations against a single in-memory project."""

    def __init__(self) -> None:
        self.project: dict[str, Any] = {
            "id": b64encode_ascii("Project:1"),
            "internalId": b64encode_ascii("ProjectInternalId:1"),
            "name": f"{PREFIX}old-name",
            "entity": {"name": ORG_ENTITY, "organization": {"name": ORG}},
            "description": "old description",
            "createdAt": "2025-01-01T00:00:00",
            "updatedAt": None,
            "access": "PRIVATE",
            "allowAllArtifactTypes": True,
            "artifactTypes": {"edges": []},
        }
        self.calls: list[str] = []
        self.rename_error: Exception | None = None
        self.upsert_error: Exception | None = None

    def fragment(self) -> RegistryFragment:
        return RegistryFragment.model_validate(self.project)

    def execute_graphql(self, query: str, variables: dict[str, Any], **_: Any) -> Any:
        gql_input = variables["input"]
        if query == RENAME_REGISTRY_GQL:
            self.calls.append("rename")
            if self.rename_error:
                raise self.rename_error
            assert gql_input["oldProjectName"] == self.project["name"]
            self.project["name"] = gql_input["newProjectName"]
            return RenameRegistry.model_validate(
                {"renameProject": {"inserted": False, "project": self.project}}
            )
        if query == UPSERT_REGISTRY_GQL:
            self.calls.append("upsert")
            if self.upsert_error:
                raise self.upsert_error
            assert gql_input["name"] == self.project["name"]
            self.project["description"] = gql_input["description"]
            self.project["access"] = gql_input["access"]
            self.project["allowAllArtifactTypes"] = gql_input[
                "allowAllArtifactTypesInRegistry"
            ]
            for artifact_type in gql_input.get("artifactTypes") or []:
                self.project["artifactTypes"]["edges"].append(
                    {"node": {"name": artifact_type["name"]}}
                )
            return UpsertRegistry.model_validate(
                {"upsertModel": {"inserted": False, "project": self.project}}
            )
        raise AssertionError(f"Unexpected query: {query}")


@fixture
def server() -> FakeRegistryServer:
    return FakeRegistryServer()


@fixture
def service_api(mocker: MockerFixture, server: FakeRegistryServer) -> MagicMock:
    from wandb.apis.public.service_api import ServiceApi

    mocker.patch("wandb.sdk.artifacts._gqlutils.server_supports", return_value=True)
    mock = mocker.Mock(spec=ServiceApi)
    mock.execute_graphql.side_effect = server.execute_graphql
    return mock


@fixture
def registry(service_api: MagicMock, server: FakeRegistryServer) -> Registry:
    return Registry(
        service_api,
        organization=ORG,
        entity=ORG_ENTITY,
        name="old-name",
        attrs=server.fragment(),
    )


def name_clash_error() -> WandbApiFailedError:
    return WandbApiFailedError(f"registry with name {PREFIX}taken already exists")


def test_save_renames_before_other_changes(
    registry: Registry, server: FakeRegistryServer
):
    registry.name = "new-name"
    registry.description = "new description"

    registry.save()

    assert server.calls == ["rename", "upsert"]


def test_save_skips_upsert_when_only_name_changed(
    registry: Registry, server: FakeRegistryServer
):
    registry.name = "new-name"

    registry.save()

    assert server.calls == ["rename"]
    assert registry.name == "new-name"
    assert registry.description == "old description"


def test_save_without_rename_only_upserts(
    registry: Registry, server: FakeRegistryServer
):
    registry.description = "new description"

    registry.save()

    assert server.calls == ["upsert"]
    assert registry.description == "new description"


def test_save_rename_failure_saves_nothing(
    registry: Registry, server: FakeRegistryServer
):
    error = name_clash_error()
    server.rename_error = error

    registry.name = "taken"
    registry.description = "new description"
    registry.visibility = "restricted"

    with raises(WandbApiFailedError) as exc_info:
        registry.save()

    # The original error propagates unchanged.
    assert exc_info.value is error
    assert server.calls == ["rename"]
    assert server.project["name"] == f"{PREFIX}old-name"
    assert server.project["description"] == "old description"

    # The saved state is unchanged and the edits stay staged.
    assert registry._saved.name == "old-name"
    assert registry._saved.description == "old description"
    assert registry.name == "taken"
    assert registry.description == "new description"
    assert registry.visibility == "restricted"


def test_save_rename_failure_can_be_retried(
    registry: Registry, server: FakeRegistryServer
):
    server.rename_error = name_clash_error()
    registry.name = "taken"
    registry.description = "new description"
    with raises(WandbApiFailedError):
        registry.save()

    server.rename_error = None
    server.calls.clear()
    registry.name = "free-name"
    registry.save()

    assert server.calls == ["rename", "upsert"]
    assert server.project["name"] == f"{PREFIX}free-name"
    assert server.project["description"] == "new description"
    assert registry.name == "free-name"
    assert registry.description == "new description"


def test_save_upsert_failure_after_rename_raises_partial_save_error(
    registry: Registry, server: FakeRegistryServer
):
    upsert_error = WandbApiFailedError("upsert failed")
    server.upsert_error = upsert_error

    registry.name = "new-name"
    registry.description = "new description"
    registry.visibility = "restricted"
    registry.allow_all_artifact_types = False
    registry.artifact_types.append("model")

    with raises(ValueError) as exc_info:
        registry.save()

    error = exc_info.value
    assert error.__cause__ is upsert_error
    msg = str(error)
    assert "'old-name'" in msg
    assert "'new-name'" in msg
    for attr in (
        "description",
        "visibility",
        "allow_all_artifact_types",
        "artifact_types",
    ):
        assert repr(attr) in msg
    assert server.calls == ["rename", "upsert"]

    # The local state matches the server: renamed, other attributes unchanged.
    assert server.project["name"] == f"{PREFIX}new-name"
    assert server.project["description"] == "old description"
    for data in (registry._saved, registry._current):
        assert data.name == "new-name"
        assert data.description == "old description"
        assert data.visibility.name == "organization"
        assert data.allow_all_artifact_types is True
        assert list(data.artifact_types) == []
    assert registry.artifact_types.draft == ()


def test_save_never_saved_registry_upserts_before_rename(
    service_api: MagicMock, server: FakeRegistryServer
):
    # Without fetched data, the upsert may create the registry, so it must
    # run before the rename.
    registry = Registry(
        service_api, organization=ORG, entity=ORG_ENTITY, name="old-name"
    )
    registry.visibility = "organization"
    registry.allow_all_artifact_types = True
    registry.name = "new-name"
    registry.description = "new description"

    registry.save()

    assert server.calls == ["upsert", "rename"]
    assert server.project["name"] == f"{PREFIX}new-name"
    assert server.project["description"] == "new description"
    assert registry.name == "new-name"


def test_save_upsert_failure_without_rename_raises_value_error(
    registry: Registry, server: FakeRegistryServer
):
    server.upsert_error = WandbApiFailedError("upsert failed")
    registry.description = "new description"

    with raises(ValueError, match="Failed to save registry"):
        registry.save()


def test_save_rename_and_other_changes(registry: Registry, server: FakeRegistryServer):
    registry.name = "new-name"
    registry.description = "new description"
    registry.visibility = "restricted"
    registry.allow_all_artifact_types = False
    registry.artifact_types.append("model")

    registry.save()

    assert server.calls == ["rename", "upsert"]
    assert server.project["name"] == f"{PREFIX}new-name"
    assert server.project["description"] == "new description"
    assert server.project["access"] == "RESTRICTED"
    assert registry._saved == registry._current
    assert registry.name == "new-name"
    assert registry.description == "new description"
    assert registry.visibility == "restricted"
    assert registry.allow_all_artifact_types is False
    assert list(registry.artifact_types) == ["model"]
    assert registry.artifact_types.draft == ()
