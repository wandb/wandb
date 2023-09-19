import pytest
from utils import run_cmd, run_cmd_async, wait_for_queued_image_job_completion
from wandb.sdk.launch._launch_add import launch_add

NAMESPACE = "wandb-release-testing"
ENTITY = "launch-release-testing"
PROJECT = "release-testing"
QUEUE = "docker-queue"
JOB_NAME = "sample_job:v0"  # simple job that counts to 50


@pytest.mark.timeout(180)
def test_docker_agent_on_local_process():
    try:
        # Start launch agent
        agent_process = run_cmd_async(
            f"wandb launch-agent -q {QUEUE} -e {ENTITY} -c tests/release_tests/test_launch/local-agent-config.yml"
        )

        # Start run
        queued_run = launch_add(
            job=f"{ENTITY}/{PROJECT}/{JOB_NAME}",
            queue_name=QUEUE,
            entity=ENTITY,
            config={},
        )

        run_started = False
        for line_bytes in iter(agent_process.stdout.readline, ""):
            line = str(line_bytes)
            if "running 1" in line:
                run_started = True
            elif run_started and "running 0" in line:
                break

        completed_run = wait_for_queued_image_job_completion(
            ENTITY, PROJECT, queued_run
        )

        summary = completed_run.summary
        history = completed_run.history(pandas=False)

        assert summary["time_elapsed"]
        assert summary["avg"]
        assert len(history) == 50
        assert history[-1]["steps"] == 49
    finally:
        agent_process.kill()
        run_cmd("rm -r artifacts")
