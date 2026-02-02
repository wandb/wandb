import json
import sys
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import pytest
import wandb
from requests import HTTPError
from wandb import Api
from wandb.apis import internal
from wandb.apis._generated import ProjectFragment
from wandb.apis.public import runs
from wandb.errors import UsageError
from wandb.sdk import wandb_login
from wandb.sdk.artifacts.artifact_download_logger import ArtifactDownloadLogger
from wandb.sdk.lib import credentials, wbauth


@pytest.fixture(autouse=True)
def patch_server_features(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent unit tests from attempting to contact the real server."""
    monkeypatch.setattr(
        runs,
        "_server_provides_project_id_for_run",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        runs,
        "_server_provides_internal_id_for_project",
        lambda *args, **kwargs: False,
    )


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
    [
        "user/proj/run",  # simple
        "/user/proj/run",  # leading slash
        "user/proj:run",  # docker
        "user/proj/runs/run",  # path_url
    ],
)
@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_parse_path(path):
    user, project, run = Api()._parse_path(path)
    assert user == "user"
    assert project == "proj"
    assert run == "run"


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
def test_parse_path_docker_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        user, project, run = Api()._parse_path("proj:run")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_parse_path_user_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        user, project, run = Api()._parse_path("proj/run")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_parse_path_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        user, project, run = Api()._parse_path("proj")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "proj"


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_parse_path_id():
    with mock.patch.dict(
        "os.environ", {"WANDB_ENTITY": "mock_entity", "WANDB_PROJECT": "proj"}
    ):
        user, project, run = Api()._parse_path("run")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
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
    mock_verify_login.assert_called_once_with(
        key="1234" * 10,
        base_url="https://test-url",
    )


def test_initialize_api_uses_explicit_key(
    monkeypatch: pytest.MonkeyPatch,
):
    mock_verify_login = MagicMock()
    monkeypatch.setattr(wandb_login, "_verify_login", mock_verify_login)
    wbauth.use_explicit_auth(
        wbauth.AuthApiKey(api_key="wrong" * 8, host="https://test-url"),
        source="test",
    )

    key = "test-api-key"*8
    api = Api(api_key=key, overrides={"base_url": "https://test-url"})

    assert api.api_key == key
    mock_verify_login.assert_called_once_with(
        key=key,
        base_url="https://test-url",
    )


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary_config():
    run = wandb.apis.public.Run(
        client=wandb.Api().client,
        entity="test",
        project="test",
        run_id="test",
        attrs={"config": '{"test": "test"}'},
    )
    assert run.config == {"test": "test"}


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary__config_not_parsable():
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


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_create_run_with_dictionary__throws_error():
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


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
def test_project_id_lazy_load(monkeypatch):
    api = wandb.Api()
    mock_execute = MagicMock(
        return_value={
            "project": ProjectFragment(
                id="123",
                name="test-project",
                entity_name="test-entity",
                created_at="2021-01-01T00:00:00Z",
                is_benchmark=False,
            ).model_dump()
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


@pytest.mark.usefixtures("patch_apikey", "skip_verify_login")
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


@pytest.mark.usefixtures("skip_verify_login")
def test_access_token_property(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Test access_token property for both API key and JWT authentication."""
    # Test 1: API key auth returns None
    with mock.patch.object(
        wbauth,
        "authenticate_session",
        return_value=wbauth.AuthApiKey(
            host="https://api.wandb.ai",
            api_key="x" * 40,
        ),
    ):
        api = Api()
        assert api.access_token is None
    
    # Test 2: JWT auth returns access token and uses auth object properties
    token_file = tmp_path / "token.jwt"
    token_file.write_text("test.jwt.token")
    monkeypatch.setenv("WANDB_IDENTITY_TOKEN_FILE", str(token_file))
    
    mock_auth = wbauth.AuthIdentityTokenFile(
        host="https://custom.bdnaw.ai",
        path=str(token_file),
    )
    
    called_with = {}
    
    def mock_access_token(base_url, token_file_path, credentials_file):
        called_with["base_url"] = base_url
        called_with["token_file"] = token_file_path
        called_with["credentials_file"] = credentials_file
        return "test_access_token_12345"
    
    monkeypatch.setattr(credentials, "access_token", mock_access_token)
    
    with mock.patch.object(wbauth, "authenticate_session", return_value=mock_auth):
        api = Api()
        token = api.access_token
        
        assert token == "test_access_token_12345"
        assert called_with["base_url"] == "https://custom.bdnaw.ai"
        assert called_with["token_file"] == Path(str(token_file))
