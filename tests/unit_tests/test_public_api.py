import sys
from unittest import mock

import pytest
import wandb
from wandb import Api
from wandb.proto.wandb_internal_pb2 import ServerFeature
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


def test_thread_local_api_key():
    try:
        _thread_local_api_settings.api_key = "XXXX"
        api = Api()
        assert api.api_key == "XXXX"
    finally:
        _thread_local_api_settings.api_key = None


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_base_url_sanitization():
    with mock.patch.object(wandb, "login", mock.MagicMock()):
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
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        user, project, run = Api()._parse_path(path)
        assert user == "user"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_parse_project_path():
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        entity, project = Api()._parse_project_path("user/proj")
        assert entity == "user"
        assert project == "proj"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_parse_project_path_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        entity, project = Api()._parse_project_path("proj")
        assert entity == "mock_entity"
        assert project == "proj"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_parse_path_docker_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        user, project, run = Api()._parse_path("proj:run")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_parse_path_user_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        user, project, run = Api()._parse_path("proj/run")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_parse_path_proj():
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        user, project, run = Api()._parse_path("proj")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "proj"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_parse_path_id():
    with mock.patch.dict(
        "os.environ", {"WANDB_ENTITY": "mock_entity", "WANDB_PROJECT": "proj"}
    ):
        user, project, run = Api()._parse_path("run")
        assert user == "mock_entity"
        assert project == "proj"
        assert run == "run"


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
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
@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_from_path_project_type(path):
    with mock.patch.object(wandb, "login", mock.MagicMock()):
        project = Api().from_path(path)
        assert isinstance(project, wandb.apis.public.Project)


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_report_to_html():
    path = "test/test/reports/My-Report--XYZ"
    report = Api().from_path(path)
    report_html = report.to_html(hidden=True)
    assert "test/test/reports/My-Report--XYZ" in report_html
    assert "<button" in report_html


def test_override_base_url_passed_to_login():
    base_url = "https://wandb.space"
    with mock.patch.object(wandb, "login", mock.MagicMock()) as mock_login:
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


ENABLED_FEATURE_RESPONSE = {
    "serverInfo": {
        "features": [
            {"name": "LARGE_FILENAMES", "isEnabled": True},
            {"name": "ARTIFACT_TAGS", "isEnabled": False},
        ]
    }
}


@pytest.fixture
def mock_client(mocker):
    mock = mocker.patch("wandb.apis.public.api.RetryingClient")
    mock.return_value = mocker.Mock()
    yield mock.return_value


@pytest.fixture
def mock_client_with_enabled_features(mock_client):
    mock_client.execute.return_value = ENABLED_FEATURE_RESPONSE
    yield mock_client


NO_FEATURES_RESPONSE = {"serverInfo": {"features": []}}


@pytest.fixture
def mock_client_with_no_features(mock_client):
    mock_client.execute.return_value = NO_FEATURES_RESPONSE
    yield mock_client


@pytest.fixture
def mock_client_with_error_no_field(mock_client):
    error_msg = 'Cannot query field "features" on type "ServerInfo".'
    mock_client.execute.side_effect = Exception(error_msg)
    yield mock_client


@pytest.fixture
def mock_client_with_random_error(mock_client):
    error_msg = "Some random error"
    mock_client.execute.side_effect = Exception(error_msg)
    yield mock_client


@pytest.mark.parametrize(
    "fixture_name, feature, expected_result, expected_error",
    [
        # Test enabled features
        (
            "mock_client_with_enabled_features",
            ServerFeature.LARGE_FILENAMES,
            True,
            False,
        ),
        # Test disabled features
        (
            "mock_client_with_enabled_features",
            ServerFeature.ARTIFACT_TAGS,
            False,
            False,
        ),
        # Test features not in response
        (
            "mock_client_with_enabled_features",
            ServerFeature.ARTIFACT_REGISTRY_SEARCH,
            False,
            False,
        ),
        # Test empty features list
        ("mock_client_with_no_features", ServerFeature.LARGE_FILENAMES, False, False),
        # Test server not supporting features
        (
            "mock_client_with_error_no_field",
            ServerFeature.LARGE_FILENAMES,
            False,
            False,
        ),
        # Test other server errors
        ("mock_client_with_random_error", ServerFeature.LARGE_FILENAMES, False, True),
    ],
)
@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_server_feature_checks(
    request,
    fixture_name,
    feature,
    expected_result,
    expected_error,
):
    """Test check_server_feature with various scenarios."""
    request.getfixturevalue(fixture_name)

    if expected_error:
        with pytest.raises(Exception, match="Some random error"):
            Api()._check_server_feature_with_fallback(feature)
    else:
        result = Api()._check_server_feature_with_fallback(feature)
        assert result == expected_result
