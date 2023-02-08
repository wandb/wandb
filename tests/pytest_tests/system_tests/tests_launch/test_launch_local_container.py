from unittest.mock import MagicMock

from wandb.apis.internal import Api
from wandb.sdk.launch._project_spec import EntryPoint, compute_command_args
from wandb.sdk.launch.builder.loader import load_builder
from wandb.sdk.launch.runner.loader import load_backend


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
        api = Api()
        runner = load_backend(
            backend_name="local-container",
            api=api,
            backend_config={"SYNCHRONOUS": False},
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
        project.override_config = {}
        project.override_entrypoint = entrypoint
        project.get_single_entry_point.return_value = entrypoint
        project.override_args = {"a1": 20, "a2": 10}
        project.docker_image = "testimage"
        project.image_name = "testimage"
        project.job = "testjob"
        string_args = " ".join(compute_command_args(project.override_args))
        builder = load_builder({"type": "noop"})

        command = runner.run(
            launch_project=project, builder=builder, registry_config={}
        )
        assert f"--entrypoint {' '.join(entry_command)}" in command
        assert f"{project.docker_image} {string_args}" in command

        # test with no user provided image
        project.docker_image = None
        project.image_name = None
        command = runner.run(
            launch_project=project, builder=builder, registry_config={}
        )
        assert f"WANDB_ARGS='{string_args}'" in command
