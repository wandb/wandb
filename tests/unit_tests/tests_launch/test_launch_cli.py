import json
import os

import pytest
import wandb
from wandb.cli import cli


@pytest.mark.timeout(200)  # builds an image
@pytest.mark.parametrize(
    "args,override_config",
    [
        (["--queue", "--build"], {"registry": {"repository": "testing123"}}),
        (
            ["--queue", "--build", "--repository", "testing-override"],
            {"registry": {"url": "testing123"}},
        ),
        (["--build", "--queue"], {"docker": {"args": ["--container_arg", "9-rams"]}}),
    ],
    ids=[
        "queue default build",
        "repository override",
        "build with docker args",
    ],
)
def test_launch_build_succeeds(
    relay_server, user, monkeypatch, runner, args, override_config
):
    proj = "test"
    image_name = "fake-image123"
    base_args = [
        "https://github.com/wandb/examples.git",
        "--entity",
        user,
        "--project",
        proj,
        "--entry-point",
        "python ./examples/launch/launch-quickstart/train.py",
        "-c",
        json.dumps(override_config),
    ]

    true_repository = override_config.get("registry") and (
        override_config["registry"].get("repository")
        or override_config["registry"].get("url")
    )
    if "--repository" in args:
        true_repository = args[args.index("--repository") + 1]

    def patched_validate_docker_installation():
        return None

    def patched_build_image_with_builder(
        builder,
        launch_project,
        repository,
        entry_point,
        docker_args,
    ):
        assert builder
        assert entry_point
        assert repository == true_repository

        return image_name

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: patched_validate_docker_installation(),
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "LAUNCH_CONFIG_FILE",
        "./config/wandb/launch-config.yaml",
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "build_image_with_builder",
        lambda *args, **kwargs: patched_build_image_with_builder(*args, **kwargs),
    )

    os.environ["WANDB_PROJECT"] = proj  # required for artifact query
    run = wandb.init(project=proj)  # create project

    with runner.isolated_filesystem(), relay_server():
        os.makedirs(os.path.expanduser("./config/wandb"))
        with open(os.path.expanduser("./config/wandb/launch-config.yaml"), "w") as f:
            json.dump({"build": {"type": "docker"}}, f)

        result = runner.invoke(cli.launch, base_args + args)

        assert result.exit_code == 0
        assert "Launching run in docker with command" not in result.output
        assert "Added run to queue" in result.output
        assert f"'job': '{user}/{proj}/job-{image_name}:v0'" in result.output

    run.finish()


@pytest.mark.timeout(100)
@pytest.mark.parametrize(
    "args",
    [(["--queue=no-exist", "--build"]), (["--build"]), (["--build=builder"])],
    ids=["queue doesn't exist", "no queue flag", "builder argument"],
)
def test_launch_build_fails(
    relay_server,
    user,
    monkeypatch,
    runner,
    args,
):
    proj = "test"
    base_args = [
        "https://github.com/wandb/examples.git",
        "--entity",
        user,
        "--project",
        proj,
        "--entry-point",
        "python ./examples/launch/launch-quickstart/train.py",
    ]

    def patched_validate_docker_installation():
        return None

    def patched_build_image_with_builder(*_):
        return "fakeImage123"

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: patched_validate_docker_installation(),
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "LAUNCH_CONFIG_FILE",
        "./config/wandb/launch-config.yaml",
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "build_image_with_builder",
        lambda *args, **kwargs: patched_build_image_with_builder(*args, **kwargs),
    )

    os.environ["WANDB_PROJECT"] = proj  # required for artifact query
    run = wandb.init(project=proj)  # create project

    with runner.isolated_filesystem(), relay_server():
        result = runner.invoke(cli.launch, base_args + args)

        if "--queue=no-exist" in args:
            assert result.exit_code == 1
            assert "Error adding run to queue" in result.output
        elif args == ["--build"]:
            assert result.exit_code == 1
            assert "Build flag requires a queue to be set" in result.output
        elif args == ["--build=builder"]:
            assert result.exit_code == 2

    run.finish()
