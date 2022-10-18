import json

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.launch.runner.local_container import LocalContainerRunner


@pytest.mark.timeout(200)  # builds an image
@pytest.mark.parametrize(
    "args,override_config",
    [
        (["--build", "--queue"], {"registry": {"url": "testing123"}}),
        (
            ["--queue", "--build", "--repository", "testing-override"],
            {
                "registry": {"url": "testing123"},
                "docker": {"args": ["--container_arg", "9-rams"]},
            },
        ),
    ],
    ids=[
        "queue default build",
        "repository and docker args override",
    ],
)
def test_launch_build_succeeds(
    relay_server,
    user,
    monkeypatch,
    runner,
    args,
    override_config,
    test_settings,
    wandb_init,
):
    proj = "testing123"
    settings = test_settings({"project": proj})
    image_name = "fake-image123"
    base_args = [
        "https://github.com/wandb/examples.git",
        "--entity",
        user,
        "--project",
        proj,
        "--entry-point",
        "python ./examples/scikit/scikit-classification/train.py",
        "-c",
        json.dumps(override_config),
    ]

    true_repository = override_config.get("registry") and (
        override_config["registry"].get("repository")
        or override_config["registry"].get("url")
    )
    if "--repository" in args:
        true_repository = args[args.index("--repository") + 1]

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
        lambda: None,
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

    with runner.isolated_filesystem(), relay_server():
        run = wandb_init(settings=settings)
        result = runner.invoke(cli.launch, base_args + args)
        run.finish()

        assert result.exit_code == 0
        assert "Launching run in docker with command" not in result.output
        assert "Added run to queue" in result.output
        assert f"'job': '{user}/{proj}/job-{image_name}:v0'" in result.output


@pytest.mark.timeout(100)
@pytest.mark.parametrize(
    "args",
    [(["--build"]), (["--build=builder"])],
    ids=["no queue flag", "builder argument"],
)
def test_launch_build_fails(
    relay_server,
    user,
    monkeypatch,
    runner,
    args,
    test_settings,
    wandb_init,
):
    proj = "testing123"
    settings = test_settings({"project": proj})
    base_args = [
        "https://github.com/wandb/examples.git",
        "--entity",
        user,
        "--project",
        proj,
        "--entry-point",
        "python ./examples/scikit/scikit-classification/train.py",
    ]

    def patched_build_image_with_builder(*_):
        return "fakeImage123"

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: None,
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

    with runner.isolated_filesystem(), relay_server():
        run = wandb_init(settings=settings)
        result = runner.invoke(cli.launch, base_args + args)

        run.finish()

        if args == ["--build"]:
            assert result.exit_code == 1
            assert "Build flag requires a queue to be set" in result.output
        elif args == ["--build", "--queue=not-a-queue"]:
            assert result.exit_code == 1
            assert "Unable to push to run queue not-a-queue." in result.output
            assert "Error adding run to queue" in result.output
        elif args == ["--build=builder"]:
            assert result.exit_code == 2
            assert (
                "Option '--build' does not take a value" in result.output
                or "Error: --build option does not take a value" in result.output
            )


@pytest.mark.timeout(300)
@pytest.mark.parametrize(
    "args",
    [(["--repository=test_repo", "--resource=local"])],
    ids=["set repository"],
)
def test_launch_repository_arg(
    relay_server,
    user,
    monkeypatch,
    runner,
    args,
    test_settings,
    wandb_init,
):
    proj = "testing123"
    base_args = [
        "https://github.com/wandb/examples.git",
        "--entity",
        user,
        "--project",
        proj,
        "--entry-point",
        "python ./examples/scikit/scikit-classification/train.py",
    ]

    def patched_run(_, launch_project, builder, registry_config):
        assert registry_config.get("url") == "test_repo" or "--repository=" in args

        return "run"

    monkeypatch.setattr(
        LocalContainerRunner,
        "run",
        lambda *args, **kwargs: patched_run(*args, **kwargs),
    )

    def patched_validate_docker_installation():
        return None

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: patched_validate_docker_installation(),
    )

    settings = test_settings({"project": proj})

    with runner.isolated_filesystem(), relay_server():
        run = wandb_init(settings=settings)
        result = runner.invoke(cli.launch, base_args + args)

        if "--respository=" in args:  # incorrect param
            assert result.exit_code == 2
        else:
            assert result.exit_code == 0

        run.finish()
