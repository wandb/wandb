import json
import os
from unittest import mock

import wandb
import wandb.sdk.launch as launch
import wandb.sdk.launch._project_spec as _project_spec
from wandb.sdk.launch.utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_STORAGE_DIR,
    PROJECT_SYNCHRONOUS,
)

from .utils import fixture_open

import pytest


@pytest.fixture
def mocked_fetchable_git_repo():
    m = mock.Mock()

    def populate_dst_dir(dst_dir):
        with open(os.path.join(dst_dir, "train.py"), "w") as f:
            f.write(fixture_open("train.py").read())
        with open(os.path.join(dst_dir, "requirements.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())
        return mock.Mock()

    m.Repo.init = mock.Mock(side_effect=populate_dst_dir)
    with mock.patch.dict("sys.modules", git=m):
        yield m


@pytest.fixture
def mock_load_backend():
    def side_effect(*args, **kwargs):
        mock_props = mock.Mock()
        mock_props.args = args
        mock_props.kwargs = kwargs
        return mock_props

    with mock.patch("wandb.sdk.launch.loader.load_backend") as mock_load_backend:
        m = mock.Mock(side_effect=side_effect)
        m.run = mock.Mock(side_effect=side_effect)
        mock_load_backend.return_value = m
        yield mock_load_backend


def check_project_spec(
    project_spec, api, uri, wandb_project=None, wandb_entity=None, config=None
):
    assert project_spec.uri == uri
    expected_project = wandb_project or uri.split("/")[4]
    assert project_spec.target_project == expected_project
    expected_target_entity = wandb_entity or api.default_entity
    assert project_spec.target_entity == expected_target_entity
    if (
        config.get("config")
        and config["config"].get("overrides")
        and config["config"]["overrides"].get("run_config")
    ):
        assert project_spec.run_config == config["config"]["overrides"]["run_config"]


def check_backend_config(config, expected_backend_config):
    for key, item in config.items():
        if key not in [PROJECT_DOCKER_ARGS, PROJECT_STORAGE_DIR, PROJECT_SYNCHRONOUS]:
            assert item == expected_backend_config[key]


def check_mock_run_info(mock_with_run_info, expected_config, kwargs):
    for arg in mock_with_run_info.args:
        if isinstance(arg, _project_spec.Project):
            check_project_spec(arg, **kwargs)
        if isinstance(arg, dict):
            check_backend_config(arg, expected_config)
    for arg in mock_with_run_info.kwargs.items():
        if isinstance(arg, _project_spec.Project):
            check_project_spec(arg, **kwargs)
        if isinstance(arg, dict):
            check_backend_config(arg, expected_config)


def test_launch_base_case(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend
):

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    expected_config = {}
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {"uri": uri, "api": api}
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, expected_config, kwargs)


def test_launch_specified_project(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
    mock_load_backend,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    kwargs = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "api": api,
        "wandb_project": "new_test_project",
    }
    expected_config = {}
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, expected_config, kwargs)


def test_launch_run_config_in_spec(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    kwargs = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "api": api,
        "wandb_project": "new_test_project",
        "config": {"overrides": {"run_config": {"epochs": 3}}},
    }

    expected_runner_config = {}
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, expected_runner_config, kwargs)


def test_launch_args_supersede_config_vals(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    kwargs = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "api": api,
        "wandb_project": "new_test_project",
        "config": {
            "project": "not-this-project",
            "overrides": {"run_config": {"epochs": 3}},
        },
    }

    expected_runner_config = {}
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, expected_runner_config, kwargs)


def test_run_in_launch_context_with_config(runner, live_mock_server, test_settings):
    with runner.isolated_filesystem():
        path = "./config.json"
        with open(path, "w") as fp:
            json.dump({"epochs": 10}, fp)
        test_settings.launch = True
        test_settings.launch_config_path = path
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        assert run.config.epochs == 10
        assert run.config.lr == 0.004
        run.finish()
