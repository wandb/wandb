import json
import time

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.launch.runner.local_container import LocalContainerRunner

REPO_CONST = "test_repo"
IMAGE_CONST = "fake_image"


def patched_fetch_and_val(launch_project, api):  # dont actuall fetch
    return launch_project


def patched_docker_push(reg, tag):
    return "we fake pushed!"


@pytest.mark.timeout(200)
@pytest.mark.parametrize(
    "args,override_config",
    [
        (
            ["--build", "--queue"],
            {"registry": {"url": REPO_CONST}},
        ),
        (
            ["--queue", "--build", "--repository", REPO_CONST],
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
    wandb_init,
):
    base_args = [
        "https://foo:bar@github.com/FooTest/Foo.git",
        "--entity",
        user,
        "--entry-point",
        "python main.py",
        "--project=uncategorized",
        "-c",
        json.dumps(override_config),
    ]

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: None,
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "fetch_and_validate_project",
        lambda *args, **kwargs: patched_fetch_and_val(*args, **kwargs),
    )

    monkeypatch.setattr(
        "wandb.docker.push",
        lambda reg, tag: patched_docker_push(reg, tag),
    )

    with runner.isolated_filesystem(), relay_server():
        run = wandb_init()
        result = runner.invoke(cli.launch, base_args + args)

        assert result.exit_code == 0
        assert "Pushing image test_repo:" in result.output
        assert "Launching run in docker with command" not in result.output
        assert "Added run to queue default." in result.output
        assert "'uri': None" in result.output
        assert f"'job': '{user}/uncategorized/job-{REPO_CONST}_" in result.output

        run.finish()


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
    wandb_init,
):
    base_args = [
        "https://foo:bar@github.com/FooTest/Foo.git",
        "--entity",
        user,
        "--entry-point",
        "python main.py",
    ]

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: None,
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "fetch_and_validate_project",
        lambda *args, **kwargs: patched_fetch_and_val(*args, **kwargs),
    )

    with runner.isolated_filesystem(), relay_server():
        run = wandb_init()
        time.sleep(1)
        result = runner.invoke(cli.launch, base_args + args)

        if args == ["--build"]:
            assert result.exit_code == 1
            assert "Build flag requires a queue to be set" in result.output
        elif args == ["--build=builder"]:
            assert result.exit_code == 2
            assert (
                "Option '--build' does not take a value" in result.output
                or "Error: --build option does not take a value" in result.output
            )
        run.finish()


@pytest.mark.timeout(300)
@pytest.mark.parametrize(
    "args",
    [(["--repository=test_repo", "--resource=local"]), (["--repository="])],
    ids=["set repository", "set repository empty"],
)
def test_launch_repository_arg(
    relay_server,
    monkeypatch,
    runner,
    args,
    wandb_init,
):
    base_args = ["https://foo:bar@github.com/FooTest/Foo.git"]

    def patched_run(_, launch_project, builder, registry_config):
        assert registry_config.get("url") == "test_repo" or "--repository=" in args

        return "run"

    monkeypatch.setattr(
        LocalContainerRunner,
        "run",
        lambda *args, **kwargs: patched_run(*args, **kwargs),
    )

    monkeypatch.setattr(
        wandb.sdk.launch.launch,
        "fetch_and_validate_project",
        lambda *args, **kwargs: patched_fetch_and_val(*args, **kwargs),
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: None,
    )

    with runner.isolated_filesystem(), relay_server():
        run = wandb_init()
        result = runner.invoke(cli.launch, base_args + args)

        if "--respository=" in args:  # incorrect param
            assert result.exit_code == 2
        else:
            assert result.exit_code == 0

        run.finish()
