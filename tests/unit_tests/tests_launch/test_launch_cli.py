import json
import os
import time
from unittest import mock

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.launch.runner.local_container import LocalContainerRunner

REPO_CONST = "test_repo"
IMAGE_CONST = "fake_image"


@pytest.fixture
def mocked_fetchable_git_repo():
    m = mock.Mock()

    def fixture_open(path, mode="r"):
        """Returns an opened fixture file"""
        return open(fixture_path(path), mode)

    def fixture_path(path):
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            os.pardir,
            os.pardir,
            "unit_tests_old",
            "assets",
            "fixtures",
            path,
        )

    def populate_dst_dir(dst_dir):
        repo = mock.Mock()
        reference = mock.Mock()
        reference.name = "master"
        repo.references = [reference]

        def create_remote(o, r):
            origin = mock.Mock()
            origin.refs = {"master": mock.Mock()}
            return origin

        repo.create_remote = create_remote
        repo.heads = {"master": mock.Mock()}
        with open(os.path.join(dst_dir, "train.py"), "w") as f:
            f.write(fixture_open("train.py").read())
        with open(os.path.join(dst_dir, "requirements.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())
        with open(os.path.join(dst_dir, "patch.txt"), "w") as f:
            f.write("test")
        return repo

    m.Repo.init = mock.Mock(side_effect=populate_dst_dir)
    with mock.patch.dict("sys.modules", git=m):
        yield m


def patched_docker_push(repo, tag):
    assert repo == REPO_CONST

    raise Exception(str(repo) + " : " + str(tag))

    return repo


def patched_build_image_with_builder(
    builder,
    launch_project,
    repository,
    entry_point,
    docker_args,
):
    assert builder
    assert entry_point

    return IMAGE_CONST


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
    test_settings,
    wandb_init,
    mocked_fetchable_git_repo,
):
    proj = "testing_build_succeeds"
    settings = test_settings({"project": proj})
    base_args = [
        "https://foo:bar@github.com/FooTest/Foo.git",
        "--entity",
        user,
        "--project",
        proj,
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
        time.sleep(1)

        result = runner.invoke(cli.launch, base_args + args)

        assert result.exit_code == 0
        assert "Launching run in docker with command" not in result.output
        assert "Added run to queue" in result.output
        assert f"'job': '{user}/{proj}/job-{IMAGE_CONST}:v0'" in result.output

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
    test_settings,
    wandb_init,
    mocked_fetchable_git_repo,
):
    proj = "testing123"
    settings = test_settings({"project": proj})
    base_args = [
        "https://foo:bar@github.com/FooTest/Foo.git",
        "--entity",
        user,
        "--project",
        proj,
    ]

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
        time.sleep(1)
        result = runner.invoke(cli.launch, base_args + args)

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
        run.finish()


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
    mocked_fetchable_git_repo,
):
    proj = "testing123"
    base_args = [
        "https://foo:bar@github.com/FooTest/Foo.git",
        "--entity",
        user,
        "--project",
        proj,
    ]

    def patched_run(_, launch_project, builder, registry_config):
        assert registry_config.get("url") == "test_repo" or "--repository=" in args

        return "run"

    monkeypatch.setattr(
        LocalContainerRunner,
        "run",
        lambda *args, **kwargs: patched_run(*args, **kwargs),
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: None,
    )

    monkeypatch.setattr(
        wandb.docker,
        "push",
        lambda repo, tag: patched_docker_push(repo, tag),
    )

    monkeypatch.setattr(wandb.docker, "tag", lambda x, y: "")

    monkeypatch.setattr(
        wandb.docker,
        "run",
        lambda *args, **kwargs: None,
    )

    settings = test_settings({"project": proj})

    with runner.isolated_filesystem(), relay_server():
        run = wandb_init(settings=settings)
        time.sleep(1)
        result = runner.invoke(cli.launch, base_args + args)

        # raise Exception(result.output)

        if "--respository=" in args:  # incorrect param
            assert result.exit_code == 2
        else:
            assert result.exit_code == 0

        run.finish()
