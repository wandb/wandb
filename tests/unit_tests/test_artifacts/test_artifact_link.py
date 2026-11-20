from __future__ import annotations

from unittest.mock import Mock

from pytest import MonkeyPatch, fixture, raises
from wandb.errors import CommError
from wandb.proto import wandb_api_pb2
from wandb.sdk.artifacts import artifact as artifact_module
from wandb.sdk.artifacts._gqlutils import OrgInfo
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.artifacts.artifact_state import ArtifactState
from wandb.sdk.lib.service.service_connection import WandbApiFailedError


@fixture
def service_api() -> Mock:
    api = Mock()
    api.app_url = "https://app.example.com/"
    return api


@fixture
def artifact(monkeypatch: MonkeyPatch, service_api: Mock) -> Artifact:
    monkeypatch.setattr(
        artifact_module,
        "_resolve_org_info",
        lambda *_: OrgInfo(org_name="my-org", entity_name="my-org-entity"),
    )
    monkeypatch.setattr(
        artifact_module, "link_artifact_gql_options", lambda *_: (set(), set())
    )

    art = Artifact("my-artifact", type="model")
    art._id = "artifact-id"
    art._state = ArtifactState.COMMITTED
    art._source_entity = "my-team"
    art._service_api = service_api
    return art


def _link_error(code: str = "") -> WandbApiFailedError:
    response = wandb_api_pb2.ApiErrorResponse(
        message='registry "my-registry" not found in organization "my-org"',
        http_status=404,
        graphql_error_code=code,
    )
    return WandbApiFailedError(response.message, response)


def test_link_to_missing_registry_raises_actionable_error(
    artifact: Artifact, service_api: Mock
):
    error = _link_error("REGISTRY_NOT_FOUND")
    service_api.execute_graphql.side_effect = error

    with raises(CommError) as exc_info:
        artifact.link("wandb-registry-my-registry/my-collection")

    assert str(exc_info.value) == (
        "Registry 'my-registry' not found in organization 'my-org'. "
        "To create it, use wandb.Api().create_registry(name='my-registry', "
        "visibility=\"organization\", organization='my-org') or visit "
        "https://app.example.com/orgs/my-org/registry"
    )
    assert exc_info.value.__cause__ is error


def test_link_error_without_registry_code_keeps_server_message(
    artifact: Artifact, service_api: Mock
):
    service_api.execute_graphql.side_effect = _link_error()

    with raises(CommError) as exc_info:
        artifact.link("wandb-registry-my-registry/my-collection")

    assert str(exc_info.value) == (
        'registry "my-registry" not found in organization "my-org"'
    )
