from unittest.mock import MagicMock

from wandb.apis.internal import Api
from wandb.sdk.launch.builder.loader import load_builder
from wandb.sdk.launch.runner.loader import load_backend
from wandb.sdk.launch._project_spec import EntryPoint


def test_local_container_entrypoint(relay_server, monkeypatch, assets_path):
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
        project.override_args = ["a1", "a2"]
        project.docker_image = "testimage"
        project.job = "testjob"
        string_args = " ".join(project.override_args)
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


def setup_mock_run_local_container(monkeypatch):
    def mock_run_entrypoint(*args, **kwargs):
        # return first arg, which is command
        return args[0]

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container._run_entrypoint",
        mock_run_entrypoint,
    )
