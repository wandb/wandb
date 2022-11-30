import json
import os
from unittest import mock

import pytest
import wandb
from wandb.apis.public import Api as PublicApi
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.launch_add import launch_add


@pytest.fixture
def mocked_fetchable_git_repo():
    m = mock.Mock()

    def fixture_open(path, mode="r"):
        """Returns an opened fixture file"""
        return open(fixture_path(path), mode)

    def fixture_path(path):
        print(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                os.pardir,
                os.pardir,
                "unit_tests_old",
                "assets",
                "fixtures",
                path,
            )
        )
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


def test_launch_add_delete_queued_run(
    relay_server, runner, user, monkeypatch, wandb_init, test_settings
):
    queue = "default"
    proj = "test2"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
    settings = test_settings({"project": proj})

    api = InternalApi()

    with relay_server():
        run = wandb_init(settings=settings)
        api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )

        queued_run = launch_add(
            uri=uri,
            entity=user,
            project=proj,
            queue_name=queue,
            entry_point=entry_point,
        )

        assert queued_run.state == "pending"

        queued_run.delete()

        run.finish()


@pytest.mark.timeout(200)
@pytest.mark.parametrize(
    "launch_config,override_config",
    [
        (
            {"build": {"type": "docker"}},
            {"docker": {"args": ["--container_arg", "9 rams"]}},
        ),
        ({}, {"cuda": False, "overrides": {"args": ["--runtime", "nvidia"]}}),
        (
            {"build": {"type": "docker"}},
            {"cuda": False, "overrides": {"args": ["--runtime", "nvidia"]}},
        ),
        ({"build": {"type": ""}}, {}),
    ],
)
def test_launch_build_push_job(
    relay_server,
    user,
    monkeypatch,
    runner,
    launch_config,
    override_config,
    mocked_fetchable_git_repo,
    wandb_init,
    test_settings,
):
    release_image = "THISISANIMAGETAG"
    queue = "test_queue"
    proj = "test8"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]
    settings = test_settings({"project": proj})
    internal_api = InternalApi()
    public_api = PublicApi()

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
        assert uri == launch_project.uri
        assert entry_point
        if override_config and override_config.get("docker"):
            assert docker_args == override_config.get("docker").get("args")

        return release_image

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

    with relay_server(), runner.isolated_filesystem():
        # create project
        run = wandb_init(settings=settings)

        os.makedirs(os.path.expanduser("./config/wandb"))
        with open(os.path.expanduser("./config/wandb/launch-config.yaml"), "w") as f:
            json.dump(launch_config, f)

        internal_api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )

        queued_run = launch_add(
            uri=uri,
            entity=user,
            project=proj,
            queue_name=queue,
            build=True,
            job="DELETE ME",
            entry_point=entry_point,
            config=override_config,
        )

        assert queued_run.state == "pending"
        assert queued_run.entity == user
        assert queued_run.project == proj
        assert queued_run.container_job is True

        rqi = internal_api.pop_from_run_queue(queue, user, proj)

        assert rqi["runSpec"]["uri"] is None
        assert rqi["runSpec"]["job"] != "DELETE ME"
        assert rqi["runSpec"]["job"].split("/")[-1] == f"job-{release_image}:v0"

        job = public_api.job(rqi["runSpec"]["job"])
        run.finish()

        assert job._source_info["source"]["image"] == release_image


def test_launch_add_default(
    relay_server, user, mocked_fetchable_git_repo, wandb_init, test_settings
):
    proj = "test_project1"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]
    args = {
        "uri": uri,
        "project": proj,
        "entity": user,
        "queue_name": "default",
        "entry_point": entry_point,
    }
    settings = test_settings({"project": proj})

    with relay_server() as relay:
        run = wandb_init(settings=settings)
        queued_run = launch_add(**args)
        run.finish()

    assert queued_run.id
    assert queued_run.state == "pending"
    assert queued_run.entity == args["entity"]
    assert queued_run.project == args["project"]
    assert queued_run.queue_name == args["queue_name"]

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        # below should fail for non-existent default queue,
        # then fallback to legacy method
        if q and "mutation pushToRunQueueByName(" in str(q):
            assert comm["response"].get("data", {}).get("pushToRunQueueByName") is None
        elif q and "mutation pushToRunQueue(" in str(q):
            assert comm["response"]["data"]["pushToRunQueue"] is not None


def test_push_to_runqueue_exists(
    relay_server, user, mocked_fetchable_git_repo, wandb_init, test_settings
):
    proj = "test_project2"
    queue = "existing-queue"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]
    args = {
        "uri": uri,
        "project": proj,
        "entity": user,
        "queue": "default",
        "entry_point": entry_point,
        "resource": "local-process",
    }

    settings = test_settings({"project": proj})

    with relay_server() as relay:
        run = wandb_init(settings=settings)
        api = wandb.sdk.internal.internal_api.Api()
        api.create_run_queue(entity=user, project=proj, queue_name=queue, access="USER")

        result = api.push_to_run_queue(queue, args)

        assert result["runQueueItemId"]

        run.finish()

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        if q and "mutation pushToRunQueueByName(" in str(q):
            assert comm["response"]["data"] is not None
        elif q and "mutation pushToRunQueue(" in str(q):
            raise Exception("should not be falling back to legacy here")


def test_push_to_default_runqueue_notexist(
    relay_server, user, mocked_fetchable_git_repo, test_settings, wandb_init
):
    api = wandb.sdk.internal.internal_api.Api()
    proj = "test_project54"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]

    settings = test_settings({"project": proj})

    launch_spec = {
        "uri": uri,
        "entity": user,
        "project": proj,
        "entry_point": entry_point,
        "resource": "local-process",
    }

    with relay_server():
        run = wandb_init(settings=settings)
        res = api.push_to_run_queue("nonexistent-queue", launch_spec)
        run.finish()

        assert not res


def test_push_to_runqueue_old_server(
    relay_server,
    user,
    monkeypatch,
    mocked_fetchable_git_repo,
    test_settings,
    wandb_init,
):
    proj = "test_project0"
    queue = "existing-queue"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]
    args = {
        "uri": uri,
        "project": proj,
        "entity": user,
        "queue": "default",
        "entry_point": entry_point,
        "resource": "local-process",
    }
    settings = test_settings({"project": proj})

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api.push_to_run_queue_by_name",
        lambda *args: None,
    )

    with relay_server():
        run = wandb_init(settings=settings)
        api = wandb.sdk.internal.internal_api.Api()

        api.create_run_queue(entity=user, project=proj, queue_name=queue, access="USER")

        result = api.push_to_run_queue(queue, args)
        run.finish()

        assert result["runQueueItemId"]


def test_push_with_repository(
    relay_server, user, mocked_fetchable_git_repo, test_settings, wandb_init
):
    api = wandb.sdk.internal.internal_api.Api()
    proj = "test_project99"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]

    launch_spec = {
        "uri": uri,
        "entity": user,
        "project": proj,
        "entry_point": entry_point,
        "registry": {"url": "repo123"},
    }
    settings = test_settings({"project": proj})

    with relay_server():
        run = wandb_init(settings=settings)
        res = api.push_to_run_queue("nonexistent-queue", launch_spec)
        run.finish()

        assert not res


def test_launch_add_repository(
    relay_server, runner, user, monkeypatch, wandb_init, test_settings
):
    queue = "default"
    proj = "test1"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
    settings = test_settings({"project": proj})
    api = InternalApi()

    with relay_server():
        run = wandb_init(settings=settings)
        api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )

        queued_run = launch_add(
            uri=uri,
            entity=user,
            project=proj,
            entry_point=entry_point,
            repository="testing123",
        )

        assert queued_run.state == "pending"

        queued_run.delete()
        run.finish()
