import json
import sys
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock

import pytest
import wandb
from wandb import Api
from wandb.apis._generated import ProjectFragment, UserFragment
from wandb.errors import UsageError
from wandb.proto import wandb_api_pb2 as apb
from wandb.sdk import wandb_login
from wandb.sdk.artifacts.artifact_download_logger import ArtifactDownloadLogger
from wandb.sdk.launch.utils import LAUNCH_DEFAULT_PROJECT
from wandb.sdk.lib import wbauth
from wandb.sdk.lib.service.service_connection import WandbApiFailedError


def test_api_auto_login_no_tty():
    with mock.patch.object(sys, "stdin", None):
        with pytest.raises(UsageError):
            Api()


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_base_url_sanitization():
    api = Api({"base_url": "https://wandb.corp.net///"})
    assert api.settings["base_url"] == "https://wandb.corp.net"


@pytest.mark.parametrize(
    "path",
    (
        "user/proj/runs/run",  # URL style
        "user/proj/run",  # regular path
        "/user/proj/run",  # leading slash
        "user/proj:run",  # docker
    ),
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_parse_path(path: str):
    user, project, run = Api()._parse_path(path)
    assert user == "user"
    assert project == "proj"
    assert run == "run"


@pytest.mark.parametrize(
    "path",
    (
        "",
        "    ",
        ":",
        "/",
        "//",
        "/ /",
        "/ / /",
        "entity/project:",
    ),
)
@pytest.mark.usefixtures("skip_verify_login")
def test_parse_path_invalid(path: str):
    api = Api(
        api_key="fake" * 10,
        overrides={
            "entity": "test-default-entity",
            "project": "test-default-project",
        },
    )

    with pytest.raises(ValueError):
        api._parse_path(path)


@pytest.mark.parametrize(
    "path",
    (
        "project/run",
        "project:run",
    ),
)
@pytest.mark.usefixtures("skip_verify_login")
def test_parse_path_default_entity(path: str):
    api = Api(
        api_key="fake" * 10,
        overrides={"entity": "test-default-entity"},
    )

    user, project, run = api._parse_path(path)

    assert user == "test-default-entity"
    assert project == "project"
    assert run == "run"


@pytest.mark.parametrize(
    "path",
    (
        "project/run",
        "project:run",
        "run",
    ),
)
@pytest.mark.usefixtures("skip_verify_login")
def test_parse_path_no_entity(path: str):
    api = Api(api_key="fake" * 10)
    api._default_entity = ""

    with pytest.raises(ValueError, match="missing entity"):
        api._parse_path(path)


@pytest.mark.usefixtures("skip_verify_login")
def test_parse_path_default_project():
    api = Api(
        api_key="fake" * 10,
        overrides={
            "entity": "test-default-entity",
            "project": "test-default-project",
        },
    )

    user, project, run = api._parse_path("run")

    assert user == "test-default-entity"
    assert project == "test-default-project"
    assert run == "run"


@pytest.mark.usefixtures("skip_verify_login")
def test_parse_path_no_project():
    api = Api(
        api_key="fake" * 10,
        overrides={"entity": "test-default-entity"},
    )

    with pytest.raises(ValueError, match="missing project"):
        api._parse_path("run")


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_parse_project_path():
    entity, project = Api()._parse_project_path("user/proj")
    assert entity == "user"
    assert project == "proj"


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_parse_project_path_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        entity, project = Api()._parse_project_path("proj")
        assert entity == "mock_entity"
        assert project == "proj"


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_direct_specification_of_api_key():
    # test_settings has a different API key
    api = Api(api_key="abcd" * 10)
    assert api.api_key == "abcd" * 10
    # The key must reach the settings wandb-core receives, not just the Api.
    assert api._service_api._settings.api_key == "abcd" * 10
    assert api._service_api._settings.to_proto().api_key.value == "abcd" * 10


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_public_api_sends_first_party_user_agent():
    # The backend gates first-party fields (e.g. a user's apiKeys) on a
    # recognized W&B client User-Agent, so the Public API must set it when
    # routing GraphQL through wandb-core (whose default User-Agent is rejected).
    headers = Api()._service_api._settings.x_extra_http_headers
    assert headers["User-Agent"] == f"W&B Public Client {wandb.__version__}"
    assert headers["Use-Admin-Privileges"] == "true"


@pytest.mark.parametrize(
    "path",
    [
        "test",
        "test/test",
    ],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_from_path_project_type(path):
    project = Api().from_path(path)
    assert isinstance(project, wandb.apis.public.Project)


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_report_to_html():
    path = "test/test/reports/My-Report--XYZ"
    report = Api().from_path(path)
    report_html = report.to_html(hidden=True)
    assert "test/test/reports/My-Report--XYZ" in report_html
    assert "<button" in report_html


def test_artifact_download_logger():
    now = 0
    termlog = mock.Mock()

    nfiles = 10
    logger = ArtifactDownloadLogger(
        nfiles=nfiles,
        clock_for_testing=lambda: now,
        termlog_for_testing=termlog,
    )

    times_calls = [
        (0, None),
        (0.001, None),
        (1, mock.call("\\ 3 of 10 files downloaded...\r", newline=False)),
        (1.001, None),
        (2, mock.call("| 5 of 10 files downloaded...\r", newline=False)),
        (2.001, None),
        (3, mock.call("/ 7 of 10 files downloaded...\r", newline=False)),
        (4, mock.call("- 8 of 10 files downloaded...\r", newline=False)),
        (5, mock.call("\\ 9 of 10 files downloaded...\r", newline=False)),
        (6, mock.call("  10 of 10 files downloaded.  ", newline=True)),
    ]
    assert len(times_calls) == nfiles

    for t, call in times_calls:
        now = t
        termlog.reset_mock()
        logger.notify_downloaded()
        if call:
            termlog.assert_called_once()
            assert termlog.call_args == call
        else:
            termlog.assert_not_called()


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_public_api_create_custom_chart():
    api = Api()
    api._service_api = MagicMock()
    api._service_api.send_api_request.return_value = apb.ApiResponse(
        create_custom_chart_response=apb.CreateCustomChartResponse(
            chart_id="test-entity/chart"
        )
    )

    chart_id = api.create_custom_chart(
        entity="test-entity",
        name="chart",
        display_name="Chart",
        spec_type="vega2",
        access="private",
        spec={"mark": "bar"},
    )

    assert chart_id == "test-entity/chart"
    api._service_api.send_api_request.assert_called_once()
    request = api._service_api.send_api_request.call_args.args[0]
    assert request.WhichOneof("request") == "create_custom_chart_request"
    create_chart = request.create_custom_chart_request
    assert create_chart.entity == "test-entity"
    assert create_chart.name == "chart"
    assert create_chart.display_name == "Chart"
    assert create_chart.spec_type == "vega2"
    assert create_chart.access == "PRIVATE"
    assert create_chart.spec == json.dumps({"mark": "bar"})


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_public_api_create_run_queue():
    api = Api()
    api._service_api = MagicMock()
    api.create_project = MagicMock()
    api._service_api.send_api_request.side_effect = [
        apb.ApiResponse(
            run_queue_operation_response=apb.RunQueueOperationResponse(
                create_default_resource_config_response=apb.CreateDefaultResourceConfigResponse(
                    success=True,
                    default_resource_config_id="config-id",
                )
            )
        ),
        apb.ApiResponse(
            run_queue_operation_response=apb.RunQueueOperationResponse(
                create_run_queue_response=apb.CreateRunQueueResponse(
                    success=True,
                    queue_id="queue-id",
                )
            )
        ),
    ]

    queue = api.create_run_queue(
        name="queue",
        type="kubernetes",
        entity="test-entity",
        prioritization_mode="V0",
        config={"image": "example"},
        template_variables={"image": {"type": "string"}},
    )

    assert queue.name == "queue"
    api.create_project.assert_called_once_with(LAUNCH_DEFAULT_PROJECT, "test-entity")
    requests = [
        call.args[0] for call in api._service_api.send_api_request.call_args_list
    ]
    assert len(requests) == 2
    assert requests[0].WhichOneof("request") == "run_queue_operation_request"
    create_config_operation = requests[0].run_queue_operation_request
    assert (
        create_config_operation.WhichOneof("operation")
        == "create_default_resource_config_request"
    )
    create_config = create_config_operation.create_default_resource_config_request
    assert create_config.entity_name == "test-entity"
    assert create_config.resource == "kubernetes"
    assert json.loads(create_config.config) == {
        "resource_args": {"kubernetes": {"image": "example"}}
    }
    assert json.loads(create_config.template_variables) == {"image": {"type": "string"}}

    assert requests[1].WhichOneof("request") == "run_queue_operation_request"
    create_queue_operation = requests[1].run_queue_operation_request
    assert create_queue_operation.WhichOneof("operation") == "create_run_queue_request"
    create_queue = create_queue_operation.create_run_queue_request
    assert create_queue.entity == "test-entity"
    assert create_queue.project == LAUNCH_DEFAULT_PROJECT
    assert create_queue.queue_name == "queue"
    assert create_queue.access == "PROJECT"
    assert create_queue.prioritization_mode == "V0"
    assert create_queue.default_resource_config_id == "config-id"
    assert create_queue.HasField("prioritization_mode")
    assert create_queue.HasField("default_resource_config_id")


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_public_api_upsert_run_queue(
    monkeypatch: pytest.MonkeyPatch,
):
    api = Api()
    api._service_api = MagicMock()
    api.create_project = MagicMock()
    api._service_api.send_api_request.return_value = apb.ApiResponse(
        run_queue_operation_response=apb.RunQueueOperationResponse(
            upsert_run_queue_response=apb.UpsertRunQueueResponse(
                success=True,
                config_schema_validation_errors=["invalid image"],
            )
        )
    )
    termwarn = MagicMock()
    monkeypatch.setattr(wandb, "termwarn", termwarn)

    queue = api.upsert_run_queue(
        name="queue",
        resource_config={"image": "example"},
        resource_type="kubernetes",
        entity="test-entity",
        template_variables={"image": {"type": "string"}},
        external_links={"docs": "https://example.test"},
        prioritization_mode="V0",
    )

    assert queue.name == "queue"
    api.create_project.assert_called_once_with(LAUNCH_DEFAULT_PROJECT, "test-entity")
    api._service_api.send_api_request.assert_called_once()
    request = api._service_api.send_api_request.call_args.args[0]
    assert request.WhichOneof("request") == "run_queue_operation_request"
    upsert_queue_operation = request.run_queue_operation_request
    assert upsert_queue_operation.WhichOneof("operation") == "upsert_run_queue_request"
    upsert_queue = upsert_queue_operation.upsert_run_queue_request
    assert upsert_queue.entity_name == "test-entity"
    assert upsert_queue.project_name == LAUNCH_DEFAULT_PROJECT
    assert upsert_queue.queue_name == "queue"
    assert upsert_queue.resource_type == "kubernetes"
    assert json.loads(upsert_queue.resource_config) == {
        "resource_args": {"kubernetes": {"image": "example"}}
    }
    assert json.loads(upsert_queue.template_variables) == {"image": {"type": "string"}}
    assert upsert_queue.prioritization_mode == "V0"
    assert json.loads(upsert_queue.external_links) == {
        "links": [{"label": "docs", "url": "https://example.test"}]
    }
    termwarn.assert_called_once_with("resource config validation: invalid image")


def test_initialize_api_with_federated_identity(federated_identity):
    """Regression test for gh-11722: federated identity in wandb.Api().

    With WANDB_IDENTITY_TOKEN_FILE set and no API key configured, all
    network traffic goes through wandb-core, which exchanges the identity
    token for an access token and authenticates with it as a Bearer token.
    """
    api = Api()

    assert api.api_key is None
    assert api.default_entity == federated_identity.entity
    assert api.viewer.username == federated_identity.username
    assert federated_identity.token_exchanges >= 1
    assert federated_identity.graphql_auth_headers
    assert all(
        header == f"Bearer {federated_identity.access_token}"
        for header in federated_identity.graphql_auth_headers
    )


def test_initialize_api_authenticates(
    monkeypatch: pytest.MonkeyPatch,
):
    mock_verify_login = MagicMock()
    monkeypatch.setattr(wandb_login, "_verify_login", mock_verify_login)
    wbauth.use_explicit_auth(
        wbauth.AuthApiKey(api_key="1234" * 10, host="https://test-url"),
        source="test",
    )

    api = Api(overrides={"base_url": "https://test-url"})

    assert api.api_key == "1234" * 10
    mock_verify_login.assert_called_once()
    (auth,) = mock_verify_login.call_args.args
    assert isinstance(auth, wbauth.AuthApiKey)
    assert auth.api_key == "1234" * 10
    assert auth.host.url == "https://test-url"
    # The Api's own service API handle is reused for verification.
    assert mock_verify_login.call_args.kwargs["service_api"] is api._service_api


def test_initialize_api_uses_explicit_key(
    monkeypatch: pytest.MonkeyPatch,
):
    mock_verify_login = MagicMock()
    monkeypatch.setattr(wandb_login, "_verify_login", mock_verify_login)
    wbauth.use_explicit_auth(
        wbauth.AuthApiKey(api_key="wrong" * 8, host="https://test-url"),
        source="test",
    )

    key = "test-api-key" * 8
    api = Api(api_key=key, overrides={"base_url": "https://test-url"})

    assert api.api_key == key
    mock_verify_login.assert_called_once()
    (auth,) = mock_verify_login.call_args.args
    assert isinstance(auth, wbauth.AuthApiKey)
    assert auth.api_key == key
    assert auth.host.url == "https://test-url"
    # The Api's own service API handle is reused for verification.
    assert mock_verify_login.call_args.kwargs["service_api"] is api._service_api


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary_config():
    api = wandb.Api()
    run = wandb.apis.public.Run(
        service_api=api._service_api,
        entity="test",
        project="test",
        run_id="test",
        attrs={"config": '{"test": "test"}'},
    )
    assert run.config == {"test": "test"}


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary__config_not_parsable():
    api = wandb.Api()
    run = wandb.apis.public.Run(
        service_api=api._service_api,
        entity="test",
        project="test",
        run_id="test",
        attrs={
            "config": {"test": "test"},
        },
    )
    assert run.config == {"test": "test"}


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary__throws_error():
    api = wandb.Api()
    with pytest.raises(wandb.errors.CommError):
        wandb.apis.public.Run(
            service_api=api._service_api,
            entity="test",
            project="test",
            run_id="test",
            attrs={
                "config": 1,
            },
        )


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_api_artifact_from_id_uses_service_api(monkeypatch):
    from wandb.sdk.artifacts.artifact import Artifact

    artifact_id = "test-artifact-id"
    api = wandb.Api()
    from_id = MagicMock(return_value="artifact")
    monkeypatch.setattr(Artifact, "_from_id", from_id)

    assert api._artifact_from_id(artifact_id) == "artifact"
    from_id.assert_called_once_with(artifact_id, api._service_api)


def test_artifact_from_id_uses_service_api(monkeypatch):
    from wandb.sdk.artifacts._generated import (
        ARTIFACT_MEMBERSHIP_BY_ID_GQL,
        ArtifactMembershipByID,
    )
    from wandb.sdk.artifacts.artifact import Artifact
    from wandb.sdk.artifacts.artifact_instance_cache import artifact_instance_cache

    artifact_id = "test-artifact-id"
    artifact_instance_cache.pop(artifact_id, None)
    # The query wraps the source artifact and collection/version in a membership.
    src_art = SimpleNamespace()
    membership = SimpleNamespace(
        artifact_collection=SimpleNamespace(
            name="dataset",
            project=SimpleNamespace(
                name="project",
                entity=SimpleNamespace(name="entity"),
            ),
        ),
        version_index=3,
        artifact=src_art,
    )
    artifact_node = SimpleNamespace(artifact_membership=membership)
    # The mock returns the parsed result because parsing happens inside the service API.
    service_api = MagicMock()
    service_api.execute_graphql.return_value = SimpleNamespace(artifact=artifact_node)
    from_attrs = MagicMock(return_value="artifact")
    monkeypatch.setattr(Artifact, "_from_attrs", from_attrs)

    assert Artifact._from_id(artifact_id, service_api) == "artifact"

    service_api.execute_graphql.assert_called_once_with(
        ARTIFACT_MEMBERSHIP_BY_ID_GQL,
        variables={"id": artifact_id},
        parse=ArtifactMembershipByID.model_validate_json,
    )
    path, actual_src_art, actual_service_api = from_attrs.call_args.args
    assert path.to_str() == "entity/project/dataset:v3"
    assert actual_src_art is src_art
    assert actual_service_api is service_api
    assert from_attrs.call_args.kwargs["membership"] is membership


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_project_id_lazy_load(monkeypatch):
    from wandb.apis._generated import GetProject

    api = wandb.Api()
    # execute_graphql now parses the response into the pydantic model itself
    # (via parse=), so its return value is the already-parsed result.
    mock_execute = MagicMock(
        return_value=GetProject.model_validate(
            {
                "project": ProjectFragment(
                    id="123",
                    name="test-project",
                    entity_name="test-entity",
                    created_at="2021-01-01T00:00:00Z",
                    is_benchmark=False,
                    user=UserFragment(
                        id="123",
                        name="test-user",
                        username="test-user",
                        email="test-user@example.com",
                        admin=False,
                        flags="",
                        entity="test-entity",
                        deleted_at=None,
                        api_keys=None,
                        teams=None,
                    ),
                ).model_dump(),
            }
        )
    )
    monkeypatch.setattr(
        wandb.apis.public.api.ServiceApi,
        "execute_graphql",
        mock_execute,
    )
    project = wandb.apis.public.Project(
        service_api=api._service_api,
        entity="test-entity",
        project="test-project",
        attrs={},
    )

    assert project.id == "123"
    assert project.created_at == "2021-01-01T00:00:00Z"
    assert project.is_benchmark is False

    mock_execute.assert_called_once()


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_project_load__raises_error(monkeypatch):
    api = wandb.Api()
    error_response = apb.ApiErrorResponse(message="not found", http_status=404)
    mock_execute = MagicMock(
        side_effect=WandbApiFailedError(error_response.message, error_response)
    )
    monkeypatch.setattr(
        wandb.apis.public.api.ServiceApi,
        "execute_graphql",
        mock_execute,
    )
    project = wandb.apis.public.Project(
        service_api=api._service_api,
        entity="test-entity",
        project="test-project",
        attrs={},
    )

    with pytest.raises(ValueError):
        project._load()
