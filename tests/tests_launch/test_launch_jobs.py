import json
import os
from unittest import mock

import pytest
import wandb
from wandb.errors import LaunchError
from wandb.sdk.data_types._dtypes import TypeRegistry
import wandb.sdk.launch.launch as launch
import wandb.sdk.launch._project_spec as _project_spec

from .test_launch import (
    check_mock_run_info,
    code_download_func,
    EMPTY_BACKEND_CONFIG,
    mock_load_backend,
    mocked_fetchable_git_repo,
)

from ..utils import fixture_open


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

    launch_project = _project_spec.LaunchProject(
        None,
        "test:v0",
        api,
        {},
        "live_mock_server_entity",
        "Test_project",
        None,
        {},
        {},
        {},
        "local",
        {},
        None,
    )
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
    input_types = TypeRegistry.type_of(
        {"epochs": 2, "heavy": False, "sleep_every": 0}
    ).to_json()
    output_types = TypeRegistry.type_of({"loss": 0.2, "cool": True}).to_json()

    def job_download_func(root):
        with open(os.path.join(root, "source_info.json"), "w") as f:
            source = {
                "_version": "v0",
                "source_type": "artifact",
                "artifact": "wandb-artifact://mock_server_entity/test/runs/1/artifacts/test-artifact",
                "entrypoint": ["python", "train.py"],
                "input_types": input_types,
                "output_types": output_types,
            }
            f.write(json.dumps(source))
        with open(os.path.join(root, "requirements.frozen.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())

    mocked_public_artifact(job_download_func)
    # def mock_artifact_fetcher(client, name, type):
    #     if type == "job":
    #         job_artifact = mock.MagicMock()
    #         job_artifact.type = "job"
    #         job_artifact.download = job_download_func
    #         job_artifact.digest = "job123"
    #         return job_artifact
    #     else:
    #         code_artifact = mock.MagicMock()
    #         code_artifact.type = "code"
    #         code_artifact.download = code_download_func
    #         code_artifact.digest = "code123"
    #         return code_artifact

    # monkeypatch.setattr(
    #     wandb.apis.public.Api,
    #     "artifact",
    #     lambda *arg, **kwargs: mock_artifact_fetcher(*arg, **kwargs),
    # )
    # monkeypatch.setattr(
    #     wandb.sdk.launch._project_spec.wandb.apis.public.Api,
    #     "artifact",
    #     lambda *arg, **kwargs: mock_artifact_fetcher(*arg, **kwargs),
    # )

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
    input_types = TypeRegistry.type_of(
        {"epochs": 2, "heavy": False, "sleep_every": 0}
    ).to_json()
    output_types = TypeRegistry.type_of({"loss": 0.2, "cool": True}).to_json()

    def job_download_func(root):
        with open(os.path.join(root, "source_info.json"), "w") as f:
            source = {
                "_version": "v0",
                "source_type": "repo",
                "remote": "https://github.com/test/remote",
                "commit": "asdasdasdasd",
                "entrypoint": ["python", "train.py"],
                "input_types": input_types,
                "output_types": output_types,
            }
            f.write(json.dumps(source))
        with open(os.path.join(root, "requirements.frozen.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())

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
    input_types = TypeRegistry.type_of(
        {"epochs": 2, "heavy": False, "sleep_every": 0}
    ).to_json()
    output_types = TypeRegistry.type_of({"loss": 0.2, "cool": True}).to_json()

    def job_download_func(root):
        with open(os.path.join(root, "source_info.json"), "w") as f:
            source = {
                "_version": "v0",
                "source_type": "image",
                "image": "my-test-image:latest",
                "input_types": input_types,
                "output_types": output_types,
            }
            f.write(json.dumps(source))
        with open(os.path.join(root, "requirements.frozen.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())

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
