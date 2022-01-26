import json
import os
from unittest.mock import MagicMock

from google.cloud import aiplatform
import wandb
from wandb.errors import LaunchError
import wandb.sdk.launch.launch as launch
from wandb.sdk.launch.runner.abstract import Status
import pytest
from tests import utils

from .test_launch import mocked_fetchable_git_repo, mock_load_backend  # noqa: F401


class dotdict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def patched_get_gcp_config(config="default"):
    if config == "default":
        return {
            "properties": {
                "core": {"project": "test-project",},
                "compute": {"zone": "us-east1",},
            },
        }


def patched_docker_push(image):
    return  # noop


def mock_aiplatform_init(project, location, staging_bucket, job_dict):
    job_dict["project"] = project
    job_dict["location"] = location


def mock_aiplatform_CustomContainerTrainingJob(display_name, container_uri, job_dict):
    job_dict["display_name"] = display_name
    return dotdict(job_dict)


def setup_mock_aiplatform(monkeypatch):
    do_nothing = lambda *args, **kwargs: None
    job_dict = {
        "name": "testid-12345",
        "display_name": None,
        "location": None,
        "project": None,
        "wait": do_nothing,
        "cancel": do_nothing,
        "state": "PipelineState.PIPELINE_STATE_SUCCEEDED",
        "run": do_nothing,
        "_gca_resource": "placeholder-value",
    }

    monkeypatch.setattr(
        aiplatform,
        "init",
        lambda project, location, staging_bucket: mock_aiplatform_init(
            project, location, staging_bucket, job_dict
        ),
    )
    monkeypatch.setattr(
        aiplatform,
        "CustomContainerTrainingJob",
        lambda display_name, container_uri: mock_aiplatform_CustomContainerTrainingJob(
            display_name, container_uri, job_dict
        ),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.gcp_vertex.get_gcp_config",
        lambda config: patched_get_gcp_config(config),
    )


@pytest.mark.timeout(320)
def test_launch_gcp_vertex(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch
):
    setup_mock_aiplatform(monkeypatch)

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.gcp_vertex.docker_push",
        lambda image: patched_docker_push(image),
    )

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "resource": "gcp-vertex",
        "entity": "mock_server_entity",
        "project": "test",
        "resource_args": {
            "gcp_staging_bucket": "test-bucket",
            "gcp_artifact_repo": "test_repo",
        },
    }
    run = launch.run(**kwargs)
    assert run.id == job_dict["name"]
    assert run.name == job_dict["display_name"]
    assert run.gcp_region == job_dict["location"]
    assert run.gcp_project == job_dict["project"]
    assert run.get_status().state == "finished"
    assert run.wait()


def test_vertex_options(test_settings, monkeypatch):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "resource": "gcp-vertex",
        "entity": "mock_server_entity",
        "project": "test",
        "resource_args": {},
    }
    try:
        launch.run(**kwargs)
    except LaunchError as e:
        assert "Vertex requires a staging bucket" in str(e)

    kwargs["resource_args"]["gcp_staging_bucket"] = "test-bucket"
    try:
        launch.run(**kwargs)
    except LaunchError as e:
        assert "Vertex requires an Artifact Registry repository" in str(e)


def test_vertex_supplied_docker_image(
    test_settings, monkeypatch, mocked_fetchable_git_repo
):
    setup_mock_aiplatform(monkeypatch)

    def patched_pull_docker_image(docker_image):
        return  # noop

    def patched_docker_image_inspect(image):
        return {
            "ContainerConfig": {"WorkingDir": "/", "Env": [],},
        }

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.gcp_vertex.pull_docker_image",
        lambda docker_image: patched_pull_docker_image(docker_image),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.gcp_vertex.docker_image_inspect",
        lambda docker_image: patched_docker_image_inspect(docker_image),
    )

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "resource": "gcp-vertex",
        "entity": "mock_server_entity",
        "project": "test",
        "docker_image": "test:tag",
        "resource_args": {
            "gcp_staging_bucket": "test-bucket",
            "gcp_artifact_repo": "test_repo",
        },
    }
    launch.run(**kwargs)
