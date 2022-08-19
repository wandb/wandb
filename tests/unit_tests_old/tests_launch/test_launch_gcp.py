import subprocess

import pytest
import wandb
import wandb.sdk.launch.launch as launch
from google.cloud import aiplatform
from wandb.errors import LaunchError
from wandb.sdk.launch.runner.gcp_vertex import get_gcp_config, run_shell

from .test_launch import mock_load_backend, mocked_fetchable_git_repo  # noqa: F401

SUCCEEDED = "PipelineState.PIPELINE_STATE_SUCCEEDED"
FAILED = "PipelineState.PIPELINE_STATE_FAILED"


class MockDict(dict):
    # use a dict to mock an object
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def patched_get_gcp_config(config="default"):
    if config == "default":
        return {
            "properties": {
                "core": {
                    "project": "test-project",
                },
                "compute": {
                    "zone": "us-east1",
                },
            },
        }


def patched_docker_push(repo, tag):
    return ""  # noop


def mock_aiplatform_init(project, location, staging_bucket, job_dict):
    job_dict["project"] = project
    job_dict["location"] = location


def mock_aiplatform_CustomJob(display_name, worker_pool_specs, job_dict):
    job_dict["display_name"] = display_name
    job_dict["test_attrs"]["container_uri"] = worker_pool_specs[0]["container_spec"][
        "image_uri"
    ]
    job_dict["test_attrs"]["command"] = worker_pool_specs[0]["container_spec"][
        "command"
    ]
    job_dict["test_attrs"]["env"] = worker_pool_specs[0]["container_spec"]["env"]
    return MockDict(job_dict)


class MockGCAResource:
    def __init__(self):
        self.name = "job-name"


def setup_mock_aiplatform(status, monkeypatch):
    # patch out fns that require gcp cli/api functionality or state

    do_nothing = lambda *args, **kwargs: None
    job_dict = {
        "name": "testid-12345",
        "display_name": None,
        "location": None,
        "project": None,
        "wait": do_nothing,
        "cancel": do_nothing,
        "state": status,
        "run": do_nothing,
        "_gca_resource": MockGCAResource(),
        "test_attrs": {
            "container_uri": None,
            "command": [],
            "env": {},
        },
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
        "CustomJob",
        lambda display_name, worker_pool_specs: mock_aiplatform_CustomJob(
            display_name, worker_pool_specs, job_dict
        ),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.gcp_vertex.get_gcp_config",
        lambda config: patched_get_gcp_config(config),
    )
    return job_dict


@pytest.mark.timeout(320)
def test_launch_gcp_vertex(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch
):
    job_dict = setup_mock_aiplatform(SUCCEEDED, monkeypatch)

    monkeypatch.setattr(
        wandb.docker,
        "push",
        lambda repo, tag: patched_docker_push(repo, tag),
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
            "gcp_vertex": {
                "staging_bucket": "test-bucket",
                "artifact_repo": "test_repo",
            },
        },
    }
    run = launch.run(**kwargs)
    assert run.id == job_dict["name"]
    assert run.name == job_dict["display_name"]
    assert run.gcp_region == job_dict["location"]
    assert run.gcp_project == job_dict["project"]
    assert run.get_status().state == "finished"
    assert run.cancel() is None
    assert run.wait()
    assert run._job.test_attrs["command"] == ["python", "train.py"]


@pytest.mark.timeout(320)
def test_launch_gcp_vertex_failed(
    live_mock_server, test_settings, mocked_fetchable_git_repo, monkeypatch
):
    job_dict = setup_mock_aiplatform(FAILED, monkeypatch)

    monkeypatch.setattr(
        wandb.docker,
        "push",
        lambda repo, tag: patched_docker_push(repo, tag),
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
            "gcp_vertex": {
                "staging_bucket": "test-bucket",
                "artifact_repo": "test_repo",
            },
        },
    }
    run = launch.run(**kwargs)
    assert run.id == job_dict["name"]
    assert run.name == job_dict["display_name"]
    assert run.get_status().state == "failed"


def test_vertex_options(test_settings, monkeypatch, mocked_fetchable_git_repo):
    job_dict = setup_mock_aiplatform(SUCCEEDED, monkeypatch)

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
        "resource_args": {"gcp_vertex": {}},
    }
    try:
        launch.run(**kwargs)
    except LaunchError as e:
        assert "No Vertex resource args specified" in str(e)

    kwargs["resource_args"]["gcp_vertex"]["region"] = "us-east1"
    try:
        launch.run(**kwargs)
    except LaunchError as e:
        assert (
            "Vertex requires a staging bucket for training and dependency packages"
            in str(e)
        )

    kwargs["resource_args"]["gcp_vertex"]["staging_bucket"] = "test-bucket"
    try:
        launch.run(**kwargs)
    except LaunchError as e:
        assert "Vertex requires an Artifact Registry repository" in str(e)


def test_vertex_supplied_docker_image(
    test_settings, monkeypatch, mocked_fetchable_git_repo
):
    job_dict = setup_mock_aiplatform(SUCCEEDED, monkeypatch)

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    kwargs = {
        "api": api,
        "resource": "gcp-vertex",
        "entity": "mock_server_entity",
        "project": "test",
        "docker_image": "test:tag",
        "resource_args": {
            "gcp_vertex": {
                "staging_bucket": "test-bucket",
                "artifact_repo": "test_repo",
            },
        },
    }
    run = launch.run(**kwargs)
    assert run.id == job_dict["name"]
    assert run.name == job_dict["display_name"]
    assert run.gcp_region == job_dict["location"]
    assert run.gcp_project == job_dict["project"]
    assert run.get_status().state == "finished"


def test_run_shell():
    assert run_shell(["echo", "hello"])[0] == "hello"


def test_get_gcp_config(monkeypatch):
    def mock_gcp_config(args, stdout, stderr):
        config_str = """
is_active: true
name: default
properties:
  compute:
    zone: us-east1-b
  core:
    account: test-account
    project: test-project
"""
        return MockDict(
            {"stdout": bytes(config_str, "utf-8"), "stderr": bytes("", "utf-8")}
        )

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, stdout, stderr: mock_gcp_config(args, stdout, stderr),
    )
    result = get_gcp_config()
    assert result["properties"]["compute"]["zone"] == "us-east1-b"
    assert result["properties"]["core"]["project"] == "test-project"
