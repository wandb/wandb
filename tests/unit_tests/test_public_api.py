"""Tests for the `wandb.apis.PublicApi` module."""


from unittest import mock

import pytest
import wandb
import wandb.util
from wandb import Api


def test_api_auto_login_no_tty():
    with pytest.raises(wandb.UsageError):
        Api()


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
        enitty, project = Api()._parse_project_path("user/proj")
        assert enitty == "user"
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


@pytest.mark.parametrize(
    "path",
    [
        "test/test/test/test",
        "test/test/test/test/test",
    ],
)
def test_from_path_bad_path(user, path):
    with pytest.raises(wandb.Error, match="Invalid path"):
        Api().from_path(path)


def test_from_path_bad_report_path(user):
    with pytest.raises(wandb.Error, match="Invalid report path"):
        Api().from_path("test/test/reports/test-foo")


@pytest.mark.parametrize(
    "path",
    [
        "test/test/reports/XYZ",
        "test/test/reports/Name-foo--XYZ",
    ],
)
def test_from_path_report_type(user, path):
    report = Api().from_path(path)
    assert isinstance(report, wandb.apis.public.BetaReport)


def test_project_to_html(user):
    with mock.patch.dict("os.environ", {"WANDB_ENTITY": "mock_entity"}):
        project = Api().from_path("test")
        assert "mock_entity/test/workspace?jupyter=true" in project.to_html()


@pytest.mark.usefixtures("patch_apikey", "patch_prompt")
def test_report_to_html():
    path = "test/test/reports/My-Report--XYZ"
    report = Api().from_path(path)
    report_html = report.to_html(hidden=True)
    assert "test/test/reports/My-Report--XYZ" in report_html
    assert "<button" in report_html


@pytest.mark.xfail(reason="TODO: fix this test")
def test_run_from_tensorboard(runner, relay_server, user, api, copy_asset):
    with relay_server() as relay, runner.isolated_filesystem():
        tb_file_name = "events.out.tfevents.1585769947.cvp"
        copy_asset(tb_file_name)
        run_id = wandb.util.generate_id()
        api.sync_tensorboard(".", project="test", run_id=run_id)
        uploaded_files = relay.context.get_run_uploaded_files(run_id)
        assert uploaded_files[0].endswith(tb_file_name)
        assert len(uploaded_files) == 17


def test_override_base_url_passed_to_login():
    base_url = "https://wandb.space"
    with mock.patch.object(wandb, "login", mock.MagicMock()) as mock_login:
        api = wandb.Api(api_key=None, overrides={"base_url": base_url})
        assert mock_login.call_args[1]["host"] == base_url
        assert api.settings["base_url"] == base_url
