from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch import loader
from wandb.sdk.launch._project_spec import EntryPoint
from wandb.sdk.launch.environment.gcp_environment import GcpEnvironment


@pytest.fixture
def mock_vertex_environment():
    """Mock an instance of the GcpEnvironment class."""
    environment = MagicMock()
    environment.region.return_value = "europe-west-4"

    async def _mock_verify():
        return True

    environment.verify = _mock_verify


@pytest.mark.asyncio
async def test_vertex_resolved_submitted_job(use_local_wandb_backend, monkeypatch):
    _ = use_local_wandb_backend

    async def mock_launch_vertex_job(*args, **kwargs):
        return args[1]

    mock_env = MagicMock(spec=GcpEnvironment)
    monkeypatch.setattr(
        wandb.sdk.launch.loader,
        "environment_from_config",
        lambda *args: mock_env,
    )
    monkeypatch.setattr(
        wandb.sdk.launch.loader,
        "builder_from_config",
        lambda *args: MagicMock(),
    )
    monkeypatch.setattr(
        wandb.sdk.launch.loader,
        "registry_from_config",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container.docker_image_exists",
        lambda x: None,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container.pull_docker_image",
        lambda x: None,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.builder.noop.NoOpBuilder.build_image",
        lambda *args, **kwargs: "testimage",
    )

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.vertex_runner.launch_vertex_job",
        mock_launch_vertex_job,
    )

    entity_name = "test_entity"
    project_name = "test_project"
    entry_command = ["python", "test.py"]

    # test with user provided image
    project = MagicMock()
    entrypoint = EntryPoint("blah", entry_command)
    project.resource_args = {
        "vertex": {
            "run": {"restart_job_on_worker_restart": False},
            "spec": {
                "staging_bucket": "gs://test_bucket",
                "worker_pool_specs": [
                    {
                        "machine_spec": {
                            "machine_type": "n1-highmem-4",
                            "accelerator_type": "NVIDIA_TESLA_T4",
                            "accelerator_count": 1,
                        },
                        "replica_count": 1,
                        "container_spec": {"image_uri": "${image_uri}"},
                    }
                ],
            },
        }
    }
    project.fill_macros.return_value = project.resource_args
    project.target_entity = entity_name
    project.target_project = project_name
    project.name = None
    project.run_id = "asdasd"
    project.sweep_id = "sweeeeep"
    project.override_config = {}
    project.override_entrypoint = entrypoint
    project.override_files = {}
    project.get_job_entry_point.return_value = entrypoint
    project.override_args = ["--a1", "20", "--a2", "10"]
    project.docker_image = "testimage"
    project.image_name = "testimage"
    project.job = "testjob"
    project.queue_name = None
    project.queue_entity = None
    project.run_queue_item_id = None
    project.launch_spec = {}
    project.get_env_vars_dict.return_value = {
        "WANDB_PROJECT": project_name,
        "WANDB_ENTITY": entity_name,
        "WANDB_LAUNCH": "True",
        "WANDB_RUN_ID": "asdasd",
        "WANDB_DOCKER": "testimage",
        "WANDB_SWEEP_ID": "sweeeeep",
        "WANDB_CONFIG": "{}",
        "WANDB_LAUNCH_FILE_OVERRIDES": "{}",
        "WANDB_ARTIFACTS": '{"_wandb_job": "testjob"}',
    }
    environment = loader.environment_from_config({})
    api = Api()
    runner = loader.runner_from_config(
        "vertex",
        api,
        {"type": "vertex", "SYNCHRONOUS": False},
        environment,
        MagicMock(),
    )
    req = await runner.run(project, project.docker_image)
    assert (
        req["worker_pool_specs"][0]["machine_spec"]["accelerator_type"]
        == "NVIDIA_TESLA_T4"
    )
    env = req["worker_pool_specs"][0]["container_spec"]["env"]
    # Pop api key and base url - these are hard to control because our
    # sdk will autopopulate them from a million places.
    assert env == [
        {"name": "WANDB_PROJECT", "value": "test_project"},
        {"name": "WANDB_ENTITY", "value": "test_entity"},
        {"name": "WANDB_LAUNCH", "value": "True"},
        {"name": "WANDB_RUN_ID", "value": "asdasd"},
        {"name": "WANDB_DOCKER", "value": "testimage"},
        {"name": "WANDB_SWEEP_ID", "value": "sweeeeep"},
        {"name": "WANDB_CONFIG", "value": "{}"},
        {"name": "WANDB_LAUNCH_FILE_OVERRIDES", "value": "{}"},
        {"name": "WANDB_ARTIFACTS", "value": '{"_wandb_job": "testjob"}'},
    ]
