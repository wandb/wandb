import json
import os
from unittest import mock

import pytest
import wandb
from wandb.apis.public import Api as PublicApi
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.launch_add import launch_add
from wandb.sdk.launch.utils import LAUNCH_DEFAULT_PROJECT


@pytest.fixture
def mocked_fetchable_git_repo():
    m = mock.Mock()

    def fixture_open(path, mode="r"):
        """Return an opened fixture file."""
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
    settings = test_settings({"project": LAUNCH_DEFAULT_PROJECT})

    api = InternalApi()

    with relay_server():
        run = wandb_init(settings=settings)
        api.create_run_queue(
            entity=user,
            project=LAUNCH_DEFAULT_PROJECT,
            queue_name=queue,
            access="PROJECT",
        )

        queued_run = launch_add(
            uri=uri,
            entity=user,
            project=proj,
            queue_name=queue,
            entry_point=entry_point,
            config={"resource": "local-process"},
            project_queue=LAUNCH_DEFAULT_PROJECT,
        )

        assert queued_run.state == "pending"

        queued_run.delete()

        run.finish()


# TODO(gst): Identify root cause of (threaded?) artifact creation error
@pytest.mark.xfail(
    strict=False,
    reason="Non-deterministic, 1-2 can fail but all 4 would suggest regression.",
)
@pytest.mark.timeout(200)
@pytest.mark.parametrize(
    "launch_config,override_config",
    [
        (
            {"build": {"type": "docker"}},
            {
                "docker": {"args": ["--container_arg", "9 rams"]},
                "resource": "local-process",
            },
        ),
        (
            {},
            {
                "cuda": False,
                "overrides": {"args": ["--runtime", "nvidia"]},
                "resource": "local-process",
            },
        ),
        (
            {"build": {"type": "docker"}},
            {
                "cuda": False,
                "overrides": {"args": ["--runtime", "nvidia"]},
                "resource": "local-process",
            },
        ),
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
    settings_mr = test_settings({"project": LAUNCH_DEFAULT_PROJECT})
    # create project for artifacts
    run_artifact = wandb_init(settings=settings_mr)
    run_artifact.finish()
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
            entity=user,
            project=LAUNCH_DEFAULT_PROJECT,
            queue_name=queue,
            access="PROJECT",
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
            project_queue=LAUNCH_DEFAULT_PROJECT,
        )

        assert queued_run.state == "pending"
        assert queued_run.entity == user
        assert queued_run.project == proj
        assert queued_run.container_job is True
        assert queued_run.project_queue == LAUNCH_DEFAULT_PROJECT

        rqi = internal_api.pop_from_run_queue(queue, user, LAUNCH_DEFAULT_PROJECT)

        assert rqi["runSpec"]["uri"] is None
        assert rqi["runSpec"]["job"] != "DELETE ME"
        assert rqi["runSpec"]["job"].split("/")[-1] == f"job-{release_image}:v0"
        # rqi pushed to launch proj, but confirm it's still pointed at our end project
        assert rqi["runSpec"]["project"] == proj

        job = public_api.job(rqi["runSpec"]["job"])
        run.finish()

        assert job._source_info["source"]["image"] == release_image


def test_launch_add_default_specify(
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
        "resource": "local-container",
    }
    settings = test_settings({"project": LAUNCH_DEFAULT_PROJECT})

    with relay_server() as relay:
        run = wandb_init(settings=settings)
        queued_run = launch_add(**args)
        run.finish()

    assert queued_run.id
    assert queued_run.state == "pending"
    assert queued_run.entity == args["entity"]
    assert queued_run.project == args["project"]
    assert queued_run.queue_name == args["queue_name"]
    assert queued_run.project_queue == LAUNCH_DEFAULT_PROJECT

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        # below should fail for non-existent default queue,
        # then fallback to legacy method
        if q and "mutation pushToRunQueueByName(" in str(q):
            assert comm["response"].get("data", {}).get("pushToRunQueueByName") is None
        elif q and "mutation pushToRunQueue(" in str(q):
            assert comm["response"]["data"]["pushToRunQueue"] is not None


def test_launch_add_default_specify_project_queue(
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
        "resource": "local-container",
        "project_queue": proj,
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
    assert queued_run.project_queue == proj

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

    settings = test_settings({"project": LAUNCH_DEFAULT_PROJECT})

    with relay_server() as relay:
        run = wandb_init(settings=settings)
        api = wandb.sdk.internal.internal_api.Api()
        api.create_run_queue(
            entity=user, project=LAUNCH_DEFAULT_PROJECT, queue_name=queue, access="USER"
        )

        result = api.push_to_run_queue(queue, args, LAUNCH_DEFAULT_PROJECT)

        assert result["runQueueItemId"]

        run.finish()

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        if q and "mutation pushToRunQueueByName(" in str(q):
            assert comm["response"].get("data") is not None
        elif q and "mutation pushToRunQueue(" in str(q):
            raise Exception("should not be falling back to legacy here")


def test_push_to_default_runqueue_notexist(
    relay_server, user, mocked_fetchable_git_repo, test_settings, wandb_init
):
    api = wandb.sdk.internal.internal_api.Api()
    proj = "test_project54"
    uri = "https://github.com/FooBar/examples.git"
    entry_point = ["python", "train.py"]

    settings = test_settings({"project": LAUNCH_DEFAULT_PROJECT})

    launch_spec = {
        "uri": uri,
        "entity": user,
        "project": proj,
        "entry_point": entry_point,
        "resource": "local-process",
    }

    with relay_server():
        run = wandb_init(settings=settings)
        res = api.push_to_run_queue(
            "nonexistent-queue", launch_spec, LAUNCH_DEFAULT_PROJECT
        )
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
    settings = test_settings({"project": LAUNCH_DEFAULT_PROJECT})

    monkeypatch.setattr(
        "wandb.sdk.internal.internal_api.Api.push_to_run_queue_by_name",
        lambda *args: None,
    )

    with relay_server():
        run = wandb_init(settings=settings)
        api = wandb.sdk.internal.internal_api.Api()

        api.create_run_queue(
            entity=user, project=LAUNCH_DEFAULT_PROJECT, queue_name=queue, access="USER"
        )

        result = api.push_to_run_queue(queue, args, LAUNCH_DEFAULT_PROJECT)
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
        "resource": "sagemaker",
    }
    settings = test_settings({"project": LAUNCH_DEFAULT_PROJECT})

    with relay_server():
        run = wandb_init(settings=settings)
        res = api.push_to_run_queue(
            "nonexistent-queue", launch_spec, LAUNCH_DEFAULT_PROJECT
        )
        run.finish()

        assert not res


def test_launch_add_repository(
    relay_server, runner, user, monkeypatch, wandb_init, test_settings
):
    queue = "default"
    proj = "test1"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
    settings = test_settings({"project": LAUNCH_DEFAULT_PROJECT})
    api = InternalApi()

    with relay_server():
        run = wandb_init(settings=settings)
        api.create_run_queue(
            entity=user,
            project=LAUNCH_DEFAULT_PROJECT,
            queue_name=queue,
            access="PROJECT",
        )

        queued_run = launch_add(
            uri=uri,
            entity=user,
            project=proj,
            entry_point=entry_point,
            repository="testing123",
            config={"resource": "sagemaker"},
            project_queue=LAUNCH_DEFAULT_PROJECT,
        )

        assert queued_run.state == "pending"

        queued_run.delete()
        run.finish()


def test_display_updated_runspec(
    relay_server, user, test_settings, wandb_init, monkeypatch
):
    queue = "default"
    proj = "test1"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
    settings = test_settings({"project": proj})
    api = InternalApi()

    def push_with_drc(api, queue_name, launch_spec, project_queue):
        # mock having a DRC
        res = api.push_to_run_queue(queue_name, launch_spec, project_queue)
        res["runSpec"] = launch_spec
        res["runSpec"]["resource_args"] = {"kubernetes": {"volume": "x/awda/xxx"}}
        return res

    monkeypatch.setattr(
        wandb.sdk.launch.launch_add,
        "push_to_queue",
        lambda *args, **kwargs: push_with_drc(*args, **kwargs),
    )

    with relay_server():
        run = wandb_init(settings=settings)
        api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )

        _ = launch_add(
            uri=uri,
            entity=user,
            project=proj,
            entry_point=entry_point,
            repository="testing123",
            config={"resource": "kubernetes"},
            project_queue=proj,
        )

        run.finish()
