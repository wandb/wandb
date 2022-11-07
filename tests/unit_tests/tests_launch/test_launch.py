from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.launch_add import launch_add
from wandb.sdk.launch.launch import run
import pytest
from wandb.errors import LaunchError


def test_launch_delete_queued_run(
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


def test_launch_repository(
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


def test_launch_incorrect_backend(
    relay_server, runner, user, monkeypatch, wandb_init, test_settings
):
    proj = "test1"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
    settings = test_settings({"project": proj})
    api = InternalApi()

    monkeypatch.setattr(
        "wandb.sdk.launch.launch.fetch_and_validate_project",
        lambda _1, _2: "something",
    )

    with relay_server():
        r = wandb_init(settings=settings)

        with pytest.raises(LaunchError) as e_info:
            run(
                api,
                uri=uri,
                entity=user,
                project=proj,
                entry_point=entry_point,
                resource="testing123",
            )

        assert "Resource name not among available resources" in str(e_info)
        r.finish()
