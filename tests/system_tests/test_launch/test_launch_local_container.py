from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wandb.apis.internal import Api
from wandb.sdk.launch import loader
from wandb.sdk.launch._project_spec import EntryPoint


@pytest.mark.asyncio
async def test_local_container_entrypoint(use_local_wandb_backend, monkeypatch):
    _ = use_local_wandb_backend

    def mock_run_entrypoint(*args, **kwargs):
        # return first arg, which is command
        return args[0]

    async def mock_build_image(*args, **kwargs):
        return "testimage"

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container._run_entry_point",
        mock_run_entrypoint,
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
        mock_build_image,
    )

    entity_name = "test_entity"
    project_name = "test_project"
    entry_command = ["python", "test.py"]

    # test with user provided image
    project = MagicMock()
    entrypoint = EntryPoint("blah", entry_command)
    project.resource_args = {"local_container": {}}
    project.target_entity = entity_name
    project.target_project = project_name
    project.name = None
    project.run_id = "asdasd"
    project.sweep_id = "sweeeeep"
    project.override_config = {}
    project.override_entrypoint = entrypoint
    project.get_job_entry_point.return_value = entrypoint
    project.override_args = ["--a1", "20", "--a2", "10"]
    project.override_files = {}
    project.docker_image = "testimage"
    project.image_name = "testimage"
    project.job = "testjob"
    project.launch_spec = {}
    project.queue_name = "queue-name"
    project.queue_entity = "queue-entity"
    project.run_queue_item_id = None
    environment = loader.environment_from_config({})
    api = Api()
    runner = loader.runner_from_config(
        "local-container",
        api,
        {"type": "local-container", "SYNCHRONOUS": False},
        environment,
        MagicMock(),
    )
    command = await runner.run(project, project.docker_image)
    assert (
        f"--entrypoint {entry_command[0]} {project.docker_image} {' '.join(entry_command[1:])}"
        in command
    )

    # test with no user provided image
    command = await runner.run(project, project.docker_image)
    assert (
        f"--entrypoint {entry_command[0]} {project.docker_image} {' '.join(entry_command[1:])}"
        in command
    )
