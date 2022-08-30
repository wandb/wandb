import os
import json
import time

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.internal.internal_api import Api as InternalApi


@pytest.fixture()
def launch_queue(api=None):
    """
    Create a fixture that creates a launch queue, required for
    all launch `--queue` tests

    TODO: How to pass the username into this function? randomly generated
       so it must be passed in...
    """
    pass


@pytest.mark.timeout(300)  # builds a container
def test_launch_build_push_job(relay_server, runner, user):
    """
    Test is broken, next things to try:
        1. one worker succeeds, one worker breaks. could that mean the docker
            builder isn't happy?
    """
    queue = "test_queue"
    proj = "test_launch_build"
    args = [
        "https://github.com/gtarpenning/wandb-launch-test",
        f"--project={proj}",
        f"--entity={user}",
        f"--queue={queue}",
        "--job=oops",
        "--build",
    ]

    api = InternalApi()
    os.environ["WANDB_PROJECT"] = proj  # required for artifact query
    run = wandb.init(project=proj)
    time.sleep(1)
    with relay_server() as relay:
        api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )
        result = runner.invoke(cli.launch, args)
        run_queue = api.get_project_run_queues(entity=user, project=proj)

        assert run_queue
        assert run_queue.pop()

    run.finish()

    for comm in relay.context.raw_data:
        if comm["request"].get("query"):
            print(comm["request"].get("query"), end="")
            print("variables", comm["request"]["variables"])
            print("response", comm["response"]["data"])
            print("\n")

    assert result.exit_code == 0
    assert "'uri': None" in str(result.output)
    assert "'job': 'oops'" not in str(result.output)


@pytest.mark.timeout(300)
def test_launch_build_with_agent(relay_server, runner, user):
    queue = "test_queue"
    proj = "test_launch_build"
    config = {
        "cuda": False,
        "overrides": {"args": ["--epochs", "5"]},
    }
    args = [
        "https://github.com/gtarpenning/wandb-launch-test",
        f"--project={proj}",
        f"--entity={user}",
        "--job=oops",
        f"--queue={queue}",
        "--build",
        f"--config={json.dumps(config)}",
    ]
    api = InternalApi()
    os.environ["WANDB_PROJECT"] = proj  # required for artifact query
    run = wandb.init(project=proj)
    time.sleep(1)
    with relay_server() as relay, runner.isolated_filesystem():
        api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )
        run_queues = api.get_project_run_queues(entity=user, project=proj)
        assert run_queues.pop()

        result = runner.invoke(cli.launch, args)

        assert result.exit_code == 0
        assert "'uri': None" in str(result.output)
        assert "'job': 'oops'" not in str(result.output)

        # could use just a normal launch with the logged job

        # job = result.output.split("'job': '")[1].split("',")[0]
        # agent_result = runner.invoke(cli.launch, f"--job={job}")

        # pick it up with an agent?
        # agent_result = runner.invoke(
        #     cli.launch_agent, [f"--queues={queue}", f"--entity={user}"]
        # )
        # print(agent_result)
        # print(agent_result.output)

        # assert agent_result.exit_code == 0

    run.finish()

    for comm in relay.context.raw_data:
        if comm["request"].get("query"):
            print(comm["request"].get("query"), end="")
            print("variables", comm["request"]["variables"])
            print("response", comm["response"]["data"])
            print("\n")
