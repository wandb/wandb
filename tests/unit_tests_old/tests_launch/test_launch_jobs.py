import json
import os
import tempfile
from unittest import mock

import pytest
import wandb
import wandb.sdk.launch._project_spec as _project_spec
import wandb.sdk.launch.launch as launch
from wandb.errors import CommError, LaunchError
from wandb.sdk.data_types._dtypes import TypeRegistry
from wandb.sdk.launch.launch_add import launch_add

from tests.unit_tests_old import utils

from .test_launch import (
    EMPTY_BACKEND_CONFIG,
    check_mock_run_info,
    code_download_func,
    mock_load_backend,
    mocked_fetchable_git_repo,
)

INPUT_TYPES = TypeRegistry.type_of(
    {"epochs": 2, "heavy": False, "sleep_every": 0}
).to_json()
OUTPUT_TYPES = TypeRegistry.type_of({"loss": 0.2, "cool": True}).to_json()


@pytest.fixture
def mocked_public_artifact(monkeypatch):
    def mock_artifact_fetcher(job_download_func):
        def artifact_fetcher(client, name, type):
            if type == "job":
                job_artifact = mock.MagicMock()
                job_artifact.type = "job"
                job_artifact.download = job_download_func
                job_artifact.digest = "job123"
                return job_artifact
            else:
                code_artifact = mock.MagicMock()
                code_artifact.type = "code"
                code_artifact.download = code_download_func
                code_artifact.digest = "code123"
                return code_artifact

        monkeypatch.setattr(
            wandb.apis.public.Api,
            "artifact",
            lambda *arg, **kwargs: artifact_fetcher(*arg, **kwargs),
        )
        monkeypatch.setattr(
            wandb.sdk.launch._project_spec.wandb.apis.public.Api,
            "artifact",
            lambda *arg, **kwargs: artifact_fetcher(*arg, **kwargs),
        )

    return mock_artifact_fetcher


def test_fetch_job_fail(api):
    kwargs = {
        "uri": None,
        "job": "test:v0",
        "api": api,
        "launch_spec": {},
        "target_entity": "live_mock_server_entity",
        "target_project": "Test_project",
        "name": None,
        "docker_config": {},
        "git_info": {},
        "overrides": {},
        "resource": "local",
        "resource_args": {},
        "cuda": None,
        "run_id": None,
    }
    launch_project = _project_spec.LaunchProject(**kwargs)
    with pytest.raises(LaunchError) as e_info:
        launch_project._fetch_job()
    assert "Job test:v0 not found" in str(e_info.value)


def test_launch_job_artifact(
    live_mock_server,
    test_settings,
    mock_load_backend,
    mocked_public_artifact,
    monkeypatch,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    def job_download_func(root):
        with open(os.path.join(root, "wandb-job.json"), "w") as f:
            source = {
                "_version": "v0",
                "source_type": "artifact",
                "source": {
                    "artifact": "wandb-artifact://mock_server_entity/test/runs/1/artifacts/test-artifact",
                    "entrypoint": ["python", "train.py"],
                },
                "input_types": INPUT_TYPES,
                "output_types": OUTPUT_TYPES,
            }
            f.write(json.dumps(source))
        with open(os.path.join(root, "requirements.frozen.txt"), "w") as f:
            f.write(utils.fixture_open("requirements.txt").read())

    mocked_public_artifact(job_download_func)

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    kwargs = {
        "job": "test-job:v0",
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
    }
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, EMPTY_BACKEND_CONFIG, kwargs)


def test_launch_job_repo(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
    mock_load_backend,
    monkeypatch,
    mocked_public_artifact,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    def job_download_func(root):
        with open(os.path.join(root, "wandb-job.json"), "w") as f:
            source = {
                "_version": "v0",
                "source_type": "repo",
                "source": {
                    "git": {
                        "remote": "https://github.com/test/remote",
                        "commit": "asdasdasdasd",
                    },
                    "entrypoint": ["python", "train.py"],
                },
                "input_types": INPUT_TYPES,
                "output_types": OUTPUT_TYPES,
            }
            f.write(json.dumps(source))
        with open(os.path.join(root, "requirements.frozen.txt"), "w") as f:
            f.write(utils.fixture_open("requirements.txt").read())

    mocked_public_artifact(job_download_func)
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    kwargs = {
        "job": "test-job:v0",
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
    }
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, EMPTY_BACKEND_CONFIG, kwargs)


def test_launch_job_container(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
    mock_load_backend,
    monkeypatch,
    mocked_public_artifact,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    def job_download_func(root):
        with open(os.path.join(root, "wandb-job.json"), "w") as f:
            source = {
                "_version": "v0",
                "source_type": "image",
                "source": {"image": "my-test-image:latest"},
                "input_types": INPUT_TYPES,
                "output_types": OUTPUT_TYPES,
            }
            f.write(json.dumps(source))
        with open(os.path.join(root, "requirements.frozen.txt"), "w") as f:
            f.write(utils.fixture_open("requirements.txt").read())

    mocked_public_artifact(job_download_func)
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    kwargs = {
        "job": "test-job:v0",
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
    }
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, EMPTY_BACKEND_CONFIG, kwargs)


def test_launch_add_container_queued_run(live_mock_server, mocked_public_artifact):
    def job_download_func(root=None):
        if root is None:
            root = tempfile.mkdtemp()
        with open(os.path.join(root, "wandb-job.json"), "w") as f:
            source = {
                "_version": "v0",
                "source_type": "image",
                "source": {"image": "my-test-image:latest"},
                "input_types": INPUT_TYPES,
                "output_types": OUTPUT_TYPES,
            }
            f.write(json.dumps(source))
        with open(os.path.join(root, "requirements.frozen.txt"), "w") as f:
            f.write(utils.fixture_open("requirements.txt").read())

        return root

    mocked_public_artifact(job_download_func)

    queued_run = launch_add(job="test-job:v0")
    with pytest.raises(CommError):
        queued_run.wait_until_finished()
