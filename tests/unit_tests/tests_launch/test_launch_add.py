import wandb
from wandb.sdk.launch.launch_add import launch_add


def test_launch_add_default(relay_server, user):
    proj = "test_project"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
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


def test_push_to_runqueue_exists(relay_server, user):
    proj = "test_project"
    queue = "existing-queue"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
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


def test_push_to_default_runqueue_notexist(relay_server, user):
    api = wandb.sdk.internal.internal_api.Api()
    proj = "test_project"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]

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


def test_push_to_runqueue_old_server(relay_server, user, monkeypatch):
    proj = "test_project"
    queue = "existing-queue"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
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
