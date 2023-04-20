from unittest.mock import MagicMock

from wandb.apis.internal import Api
from wandb.sdk.launch import loader
from wandb.sdk.launch._project_spec import EntryPoint


def test_local_container_entrypoint(relay_server, monkeypatch):
    def mock_run_entrypoint(*args, **kwargs):
        # return first arg, which is command
        return args[0]

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container._run_entry_point",
        mock_run_entrypoint,
    )

    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container.pull_docker_image",
        lambda x: None,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container.docker_image_exists",
        lambda x: False,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.builder.noop.NoOpBuilder.build_image",
        lambda *args, **kwargs: "testimage",
    )

    with relay_server():
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
        project.override_config = {}
        project.override_entrypoint = entrypoint
        project.get_single_entry_point.return_value = entrypoint
        project.override_args = ["--a1", "20", "--a2", "10"]
        project.docker_image = "testimage"
        project.image_name = "testimage"
        project.job = "testjob"
        project.launch_spec = {}
        string_args = " ".join(project.override_args)
        environment = loader.environment_from_config({})
        registry = loader.registry_from_config({}, environment)
        builder = loader.builder_from_config({"type": "noop"}, environment, registry)
        api = Api()
        runner = loader.runner_from_config(
            "local-container",
            api,
            {"type": "local-container", "SYNCHRONOUS": False},
            environment,
        )
        command = runner.run(launch_project=project, builder=builder)
        assert (
            f"--entrypoint {entry_command[0]} {project.docker_image} {' '.join(entry_command[1:])}"
            in command
        )

        # test with no user provided image
        project.docker_image = None
        project.image_name = None
        command = runner.run(launch_project=project, builder=builder)
        assert f"WANDB_ARGS='{string_args}'" in command
        assert f"WANDB_ARGS='{string_args}'" in command
