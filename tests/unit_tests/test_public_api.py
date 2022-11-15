"""Tests for the `wandb.apis.PublicApi` module."""


from unittest import mock

import pytest
import wandb
import wandb.apis.public
import wandb.util
from wandb import Api

from .test_wandb_sweep import (
    SWEEP_CONFIG_BAYES,
    SWEEP_CONFIG_GRID,
    SWEEP_CONFIG_GRID_NESTED,
    SWEEP_CONFIG_RANDOM,
    VALID_SWEEP_CONFIGS_MINIMAL,
)


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


def test_artifact_download_logger():
    now = 0
    termlog = mock.Mock()

    nfiles = 10
    logger = wandb.apis.public._ArtifactDownloadLogger(
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


@pytest.mark.parametrize("sweep_config", VALID_SWEEP_CONFIGS_MINIMAL)
def test_sweep_api(user, relay_server, sweep_config):
    _project = "test"
    with relay_server():
        sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)
    print(f"sweep_id{sweep_id}")
    sweep = Api().sweep(f"{user}/{_project}/sweeps/{sweep_id}")
    assert sweep.entity == user
    assert f"{user}/{_project}/sweeps/{sweep_id}" in sweep.url
    assert sweep.state == "PENDING"
    assert str(sweep) == f"<Sweep {user}/test/{sweep_id} (PENDING)>"


@pytest.mark.parametrize(
    "sweep_config,expected_run_count",
    [
        (SWEEP_CONFIG_GRID, 3),
        (SWEEP_CONFIG_GRID_NESTED, 9),
        (SWEEP_CONFIG_BAYES, None),
        (SWEEP_CONFIG_RANDOM, None),
    ],
    ids=["test grid", "test grid nested", "test bayes", "test random"],
)
def test_sweep_api_expected_run_count(
    user, relay_server, sweep_config, expected_run_count
):
    _project = "test"
    with relay_server() as relay:
        sweep_id = wandb.sweep(sweep_config, entity=user, project=_project)

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        print(q)

    print(f"sweep_id{sweep_id}")
    sweep = Api().sweep(f"{user}/{_project}/sweeps/{sweep_id}")

    assert sweep.expected_run_count == expected_run_count


def test_update_aliases_on_artifact(user, relay_server, wandb_init):
    project = "test"
    run = wandb_init(entity=user, project=project)
    artifact = wandb.Artifact("test-artifact", "test-type")
    with open("boom.txt", "w") as f:
        f.write("testing")
    artifact.add_file("boom.txt", "test-name")
    art = run.log_artifact(artifact, aliases=["sequence"])
    run.link_artifact(art, f"{user}/{project}/my-sample-portfolio")
    artifact.wait()
    run.finish()

    # fetch artifact under original parent sequence
    artifact = Api().artifact(
        name=f"{user}/{project}/test-artifact:v0", type="test-type"
    )
    aliases = artifact.aliases
    assert "sequence" in aliases

    # fetch artifact under portfolio
    # and change aliases under portfolio only
    artifact = Api().artifact(
        name=f"{user}/{project}/my-sample-portfolio:v0", type="test-type"
    )
    aliases = artifact.aliases
    assert "sequence" not in aliases
    artifact.aliases = ["portfolio"]
    artifact.aliases.append("boom")
    artifact.save()

    artifact = Api().artifact(
        name=f"{user}/{project}/my-sample-portfolio:v0", type="test-type"
    )
    aliases = artifact.aliases
    assert "portfolio" in aliases
    assert "boom" in aliases
    assert "sequence" not in aliases
