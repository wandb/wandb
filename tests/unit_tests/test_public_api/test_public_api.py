import json
import sys
from unittest import mock
from unittest.mock import MagicMock

import pytest
import wandb
from requests import HTTPError
from wandb import Api
from wandb.apis import internal
from wandb.sdk import wandb_login
from wandb.sdk.artifacts.artifact_download_logger import ArtifactDownloadLogger
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings


def test_api_auto_login_no_tty():
    with mock.patch.object(sys, "stdin", None):
        with pytest.raises(wandb.UsageError):
            Api()


def test_thread_local_cookies():
    try:
        _thread_local_api_settings.cookies = {"foo": "bar"}
        api = Api()
        assert api._base_client.transport.cookies == {"foo": "bar"}
    finally:
        _thread_local_api_settings.cookies = None


@pytest.mark.usefixtures("skip_verify_login")
def test_thread_local_api_key():
    try:
        _thread_local_api_settings.api_key = "X" * 40
        api = Api()
        assert api.api_key == "X" * 40
    finally:
        _thread_local_api_settings.api_key = None


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_base_url_sanitization():
    api = Api({"base_url": "https://wandb.corp.net///"})
    assert api.settings["base_url"] == "https://wandb.corp.net"


@pytest.mark.parametrize(
    "path",
    [
        "user/proj/run",  # simple
        "/user/proj/run",  # leading slash
        "user/proj:run",  # docker
        "user/proj/runs/run",  # path_url
    ],
)
@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_parse_path(path):
    with mock.patch.object(
        wandb_login, "_login", mock.MagicMock(return_value=(True, None))
    ):
        user, project, run = Api()._parse_path(path)
        assert user == "user"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_parse_project_path():
    entity, project = Api()._parse_project_path("user/proj")
    assert entity == "user"
    assert project == "proj"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_parse_project_path_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        entity, project = Api()._parse_project_path("proj")
        assert entity == "mock_entity"
        assert project == "proj"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_parse_path_docker_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        user, project, run = Api()._parse_path("proj:run")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_parse_path_user_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        user, project, run = Api()._parse_path("proj/run")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_parse_path_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        user, project, run = Api()._parse_path("proj")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "proj"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_parse_path_id():
    with mock.patch.dict(
        "os.environ", {"WANDB_ENTITY": "mock_entity", "WANDB_PROJECT": "proj"}
    ):
        user, project, run = Api()._parse_path("run")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_direct_specification_of_api_key():
    # test_settings has a different API key
    api = Api(api_key="abcd" * 10)
    assert api.api_key == "abcd" * 10


@pytest.mark.parametrize(
    "path",
    [
        "test",
        "test/test",
    ],
)
@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_from_path_project_type(path):
    project = Api().from_path(path)
    assert isinstance(project, wandb.apis.public.Project)


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_report_to_html():
    path = "test/test/reports/My-Report--XYZ"
    report = Api().from_path(path)
    report_html = report.to_html(hidden=True)
    assert "test/test/reports/My-Report--XYZ" in report_html
    assert "<button" in report_html


def test_override_base_url_passed_to_login():
    base_url = "https://wandb.space"
    with mock.patch.object(
        wandb_login, "_login", mock.MagicMock(return_value=(True, None))
    ) as mock_login:
        api = wandb.Api(api_key=None, overrides={"base_url": base_url})
        assert mock_login.call_args[1]["host"] == base_url
        assert api.settings["base_url"] == base_url


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


def test_create_custom_chart(monkeypatch):
    _api = internal.Api()
    _api.api.gql = MagicMock(return_value={"createCustomChart": {"chart": {"id": "1"}}})
    mock_gql = MagicMock(return_value="test-gql-resp")
    monkeypatch.setattr(wandb.sdk.internal.internal_api, "gql", mock_gql)

    # Test with uppercase access (as would be passed from public API)
    kwargs = {
        "entity": "test-entity",
        "name": "chart",
        "display_name": "Chart",
        "spec_type": "vega2",
        "access": "PRIVATE",  # Uppercase as converted by public API
        "spec": {},
    }

    resp = _api.create_custom_chart(**kwargs)
    assert resp == {"chart": {"id": "1"}}
    _api.api.gql.assert_called_once_with(
        "test-gql-resp",
        {
            "entity": "test-entity",
            "name": "chart",
            "displayName": "Chart",
            "type": "vega2",
            "access": "PRIVATE",
            "spec": json.dumps({}),
        },
    )


def test_initialize_api_prompts_for_api_key():
    with mock.patch.object(
        wandb_login, "_login", mock.MagicMock(return_value=(True, None))
    ) as mock_login:
        Api()

        assert mock_login.call_count == 1
        assert "key" in mock_login.call_args[1]
        assert mock_login.call_args[1]["key"] is None


def test_initialize_api_does_not_prompt_for_api_key__when_api_key_is_provided():
    api_key = "X" * 40
    with mock.patch.object(
        wandb_login, "_login", mock.MagicMock(return_value=(True, api_key))
    ) as mock_login:
        api = Api(api_key=api_key)

        assert mock_login.call_count == 1
        assert "key" in mock_login.call_args[1]
        assert mock_login.call_args[1]["key"] == api_key
        assert api.api_key == api_key


def test_initialize_api_does_not_prompt_for_api_key__when_using_thread_local_settings():
    with mock.patch.object(
        wandb_login, "_login", mock.MagicMock(return_value=(True, None))
    ) as mock_login:
        _thread_local_api_settings.api_key = "X" * 40

        api = Api()

        assert mock_login.call_count == 1
        assert "key" in mock_login.call_args[1]
        assert mock_login.call_args[1]["key"] == "X" * 40
        assert api.api_key == "X" * 40


def test_initialize_api_does_not_prompt_for_api_key__when_using_env_var(monkeypatch):
    api_key = "X" * 40
    mock_login = mock.MagicMock(return_value=(True, api_key))
    monkeypatch.setattr(wandb_login, "_login", mock_login)
    monkeypatch.setattr("os.environ", {"WANDB_API_KEY": api_key})

    api = Api(overrides={"api_key": api_key})

    assert mock_login.call_count == 1
    assert "key" in mock_login.call_args[1]
    assert mock_login.call_args[1]["key"] == api_key
    assert api.api_key == api_key


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_create_run_with_dictionary_config():
    run = wandb.apis.public.Run(
        client=wandb.Api().client,
        entity="test",
        project="test",
        run_id="test",
        attrs={"config": '{"test": "test"}'},
    )
    assert run.config == {"test": "test"}


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_create_run_with_dictionary__config_not_parsable():
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        run = wandb.apis.public.Run(
            client=wandb.Api().client,
            entity="test",
            project="test",
            run_id="test",
            attrs={
                "config": {"test": "test"},
            },
        )
        assert run.config == {"test": "test"}


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_create_run_with_dictionary__throws_error():
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        with pytest.raises(wandb.errors.CommError):
            wandb.apis.public.Run(
                client=wandb.Api().client,
                entity="test",
                project="test",
                run_id="test",
                attrs={
                    "config": 1,
                },
            )


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_project_id_lazy_load(monkeypatch):
    api = wandb.Api()
    mock_execute = MagicMock(
        return_value={
            "project": {
                "id": "123",
                "createdAt": "2021-01-01T00:00:00Z",
                "isBenchmark": False,
            }
        }
    )
    monkeypatch.setattr(wandb.apis.public.api.RetryingClient, "execute", mock_execute)
    project = wandb.apis.public.Project(
        client=api.client,
        entity="test-entity",
        project="test-project",
        attrs={},
    )

    assert project.id == "123"
    assert project.created_at == "2021-01-01T00:00:00Z"
    assert project.is_benchmark is False

    mock_execute.assert_called_once()


@pytest.mark.usefixtures("patch_apikey", "patch_prompt", "skip_verify_login")
def test_project_load__raises_error(monkeypatch):
    api = wandb.Api()
    mock_execute = MagicMock(side_effect=HTTPError(response=MagicMock(status_code=404)))
    monkeypatch.setattr(wandb.apis.public.api.RetryingClient, "execute", mock_execute)
    project = wandb.apis.public.Project(
        client=api.client,
        entity="test-entity",
        project="test-project",
        attrs={},
    )

    with pytest.raises(ValueError):
        project._load()
