import json
import os

import pytest
from unittest import mock
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
):
    release_image = "THISISANIMAGETAG"
    queue = "test_queue"
    proj = "test"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]

    internal_api = InternalApi()
    public_api = PublicApi()
    os.environ["WANDB_PROJECT"] = proj  # required for artifact query

    # create project
    run = wandb.init(project=proj)

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

        assert job._source_info["source"]["image"] == release_image

    run.finish()


def test_launch_add_default(relay_server, user, mocked_fetchable_git_repo):
    proj = "test_project"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]
    args = {
        "uri": uri,
        "project": proj,
        "entity": user,
        "queue_name": "default",
        "entry_point": entry_point,
    }

    run = wandb.init(project=proj)

    with relay_server() as relay:
        queued_run = launch_add(**args)

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

    run.finish()


def test_push_to_runqueue_exists(relay_server, user, mocked_fetchable_git_repo):
    proj = "test_project"
    queue = "existing-queue"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]
    args = {
        "uri": uri,
        "project": proj,
        "entity": user,
        "queue": "default",
        "entry_point": entry_point,
    }

    run = wandb.init(project=proj)
    api = wandb.sdk.internal.internal_api.Api()

    with relay_server() as relay:
        api.create_run_queue(entity=user, project=proj, queue_name=queue, access="USER")

        result = api.push_to_run_queue(queue, args)

        assert result["runQueueItemId"]

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        if q and "mutation pushToRunQueueByName(" in str(q):
            assert comm["response"]["data"] is not None
        elif q and "mutation pushToRunQueue(" in str(q):
            raise Exception("should not be falling back to legacy here")

    run.finish()


def test_push_to_default_runqueue_notexist(
    relay_server, user, mocked_fetchable_git_repo
):
    api = wandb.sdk.internal.internal_api.Api()
    proj = "test_project"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]

    launch_spec = {
        "uri": uri,
        "entity": user,
        "project": proj,
        "entry_point": entry_point,
    }
    run = wandb.init(project=proj)

    with relay_server():
        res = api.push_to_run_queue("nonexistent-queue", launch_spec)

        assert not res

    run.finish()


def test_push_to_runqueue_old_server(
    relay_server, user, monkeypatch, mocked_fetchable_git_repo
):
    proj = "test_project"
    queue = "existing-queue"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]
    args = {
        "uri": uri,
        "project": proj,
        "entity": user,
        "queue": "default",
        "entry_point": entry_point,
    }

    run = wandb.init(project=proj)
    api = wandb.sdk.internal.internal_api.Api()

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api.push_to_run_queue_by_name",
        lambda *args: None,
    )

    with relay_server():
        api.create_run_queue(entity=user, project=proj, queue_name=queue, access="USER")

        result = api.push_to_run_queue(queue, args)

        assert result["runQueueItemId"]

    run.finish()
