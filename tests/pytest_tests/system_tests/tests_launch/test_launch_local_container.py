from unittest.mock import MagicMock

import pytest
from wandb.apis.internal import Api
from wandb.sdk.launch._project_spec import EntryPoint, compute_command_args
from wandb.sdk.launch.builder.loader import load_builder
from wandb.sdk.launch.runner.loader import load_backend


def test_local_container_entrypoint(relay_server, mock_run_local_container):
    with relay_server():
        api = Api()
        runner = load_backend(
            backend_name="local-container",
            api=api,
            backend_config={"SYNCHRONOUS": False},
        )
        entity_name = "test_entity"
        project_name = "test_project"
        entrypoint = ["python", "test.py"]

        # test with user provided image
        project = MagicMock()
        project.resource_args = {"local_container": {}}
        project.target_entity = entity_name
        project.target_project = project_name
        project.override_config = {}
        project.override_entrypoint = EntryPoint("blah", entrypoint)
        project.override_args = {"a1": 20, "a2": 10}
        project.docker_image = "testimage"
        project.job = "testjob"
        string_args = compute_command_args(project.override_args)
        builder = load_builder({"type": "noop"})

        command = runner.run(
            launch_project=project, builder=builder, registry_config={}
        )
        assert f"--entrypoint {entrypoint.join(' ')}" in command
        assert f"{project.docker_image} {string_args}" in command
        # test with our image
        project.docker_image = None
        command = runner.run(
            launch_project=project, builder=builder, registry_config={}
        )
        assert "--entrypoint" not in command
        assert f"WANDB_ARGS={string_args}" in command


@pytest.fixture
def mock_run_local_container(mocker):
    def mock_run_entrypoint(*args, **kwargs):
        # return first arg, which is command
        return args[0]

    mocker.patch(
        "wandb.sdk.launch.runner.local_container._run_entry_point",
        mock_run_entrypoint,
    )
