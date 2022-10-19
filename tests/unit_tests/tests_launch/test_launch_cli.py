import json
import time

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.launch.runner.local_container import LocalContainerRunner

REPO_CONST = "test-repo"
IMAGE_CONST = "fake-image"


def patched_fetch_and_val(launch_project, api):  # dont actuall fetch
    launch_project._image_tag = IMAGE_CONST
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
    test_settings,
):
    proj = "testing123"
    settings = test_settings({"project": proj})
    base_args = [
        "https://foo:bar@github.com/FooTest/Foo.git",
        "--entity",
        user,
        "--entry-point",
        "python main.py",
        f"--project={proj}",
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
        "wandb.docker.build",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        "wandb.docker.push",
        lambda reg, tag: patched_docker_push(reg, tag),
    )

    monkeypatch.setattr(
        "wandb.docker.run",
        lambda *args, **kwargs: "runnning",
    )

    with runner.isolated_filesystem(), relay_server() as relay:
        run = wandb_init(settings=settings)
        result = runner.invoke(cli.launch, base_args + args)

        for comm in relay.context.raw_data:
            if comm["request"].get("query"):
                print(comm["request"].get("query"), end="")
                print("variables", comm["request"]["variables"])
                print("response", comm["response"]["data"])
                print("\n")

        assert result.exit_code == 0
        assert f"Pushing image {REPO_CONST}:{IMAGE_CONST}" in result.output
        assert "Launching run in docker with command" not in result.output
        assert "Added run to queue default." in result.output
        assert "'uri': None" in result.output
        assert f"'job': '{user}/{proj}/job-{REPO_CONST}_{IMAGE_CONST}" in result.output

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

    monkeypatch.setattr(
        "wandb.docker.build",
        lambda reg, tag: None,
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
        "wandb.sdk.launch.launch.fetch_and_validate_project",
        lambda *args, **kwargs: patched_fetch_and_val(*args, **kwargs),
    )

    with runner.isolated_filesystem(), relay_server():
        run = wandb_init()
        result = runner.invoke(cli.launch, base_args + args)

        if "--respository=" in args:  # incorrect param
            assert result.exit_code == 2
        else:
            assert result.exit_code == 0

        run.finish()
