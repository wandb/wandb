import os
import signal
import subprocess
import sys

from time import sleep
from wandb.sdk.launch.launch_add import launch_add
from utils import get_wandb_api_key

ENTITY = "launch-release-testing"
PROJECT = "release-testing"
QUEUE = "kubernetes-queue"
JOB_NAME = "job-305054156030.dkr.ecr.us-east-2.amazonaws.com_release-testing_latest:v0"


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


def test_agent_run_in_cluster():
    # get user's wandb API key
    wandb_api_key = get_wandb_api_key()
    # api = client.CoreV1Api()
    # md = client.V1ObjectMeta(name="wandb")
    # ns = client.V1Namespace(metadata=md)
    # resp = api.create_namespace(ns)
    # pprint(resp)

    subprocess.Popen(["kubectl", "create", "namespace", "wandb"]).wait()
    subprocess.Popen(
        [
            "kubectl",
            "-n",
            "wandb",
            "create",
            "secret",
            "generic",
            "wandb-api-key",
            f"--from-literal=password={wandb_api_key}",
        ]
    ).wait()
    subprocess.Popen(["kubectl", "apply", "-f", "launch-config.yml"]).wait()
    subprocess.Popen(["kubectl", "apply", "-f", "launch-agent.yml"]).wait()

    # Capture sigint so cleanup occurs even on ctrl-C
    # sigint = signal.getsignal(signal.SIGINT)

    # def cleanup(signum, frame):
    #     signal.signal(signal.SIGINT, sigint)
    #     subprocess.Popen(
    #         [
    #             "kubectl",
    #             "-n",
    #             "wandb",
    #             "delete",
    #             "deploy",
    #             "launch-agent-release-testing",
    #         ]
    #     ).wait()
    #     sys.exit(1)

    # signal.signal(signal.SIGINT, cleanup)

    try:
        # Start run
        aws_id = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
        aws_token = os.getenv("AWS_SESSION_TOKEN")
        config = {
            "resource_args": {
                "kubernetes": {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "env": [
                                            {
                                                "name": "AWS_ACCESS_KEY_ID",
                                                "value": aws_id,
                                            },
                                            {
                                                "name": "AWS_SECRET_ACCESS_KEY",
                                                "value": aws_secret,
                                            },
                                            {
                                                "name": "AWS_SESSION_TOKEN",
                                                "value": aws_token,
                                            },
                                        ]
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
        queued_run = launch_add(
            job=f"{ENTITY}/{PROJECT}/{JOB_NAME}",
            queue_name=QUEUE,
            entity=ENTITY,
            config=config,
        )

        # Assert successful
        starting = True
        print("\n" * 10)
        while starting:
            print(queued_run.state)
            starting = queued_run.state in ["pending", "leased", "claimed"]
            sleep(1)
        print(queued_run.state)
        run = queued_run.wait_until_finished()
        assert run.state == "finished"
    finally:
        # Cleanup
        pass
        # subprocess.Popen(
        #     [
        #         "kubectl",
        #         "-n",
        #         "wandb",
        #         "delete",
        #         "deploy",
        #         "launch-agent-release-testing",
        #     ]
        # ).wait()


if __name__ == "__main__":
    test_agent_run_in_cluster()
