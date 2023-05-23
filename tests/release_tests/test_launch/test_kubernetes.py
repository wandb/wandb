import subprocess

from wandb.sdk.launch.launch_add import launch_add

ENTITY = "launch-release-testing"
PROJECT = "release-testing"
QUEUE = "kubernetes-queue"
JOB_NAME = "job-source-release-testing-train-np.py:v0"


def test_kubernetes_successful_run():
    try:
        # Start launch agent
        agent_cmd = ["wandb", "launch-agent", "-q", QUEUE, "-e", ENTITY]
        agent_process = subprocess.Popen(agent_cmd)

        # Start run
        queued_run = launch_add(
            job=f"{ENTITY}/{PROJECT}/{JOB_NAME}", queue_name=QUEUE, entity=ENTITY
        )

        # Assert successful
        run = queued_run.wait_until_finished()
        assert run.state == "finished"
    finally:
        agent_process.kill()
        subprocess.Popen(["rm", "-r", "artifacts"]).wait()
