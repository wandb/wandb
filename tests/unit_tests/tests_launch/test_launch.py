
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.launch_add import launch_add


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
            queue_name=queue,
            entry_point=entry_point,
            repository="testing123",
        )

        assert queued_run.state == "pending"

        queued_run.delete()
        run.finish()
