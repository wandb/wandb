import os
import signal
import subprocess
import sys

from time import sleep
from wandb.sdk.launch.launch_add import launch_add
from utils import get_wandb_api_key


def test_kubernetes_successful_run():
    entity = "launch-release-testing"
    project = "release-testing"
    queue = "kubernetes-queue"
    job_name = (
        "job-305054156030.dkr.ecr.us-east-2.amazonaws.com_release-testing_latest:v0"
    )
    try:
        # Start launch agent
        agent_cmd = ["wandb", "launch-agent", "-q", queue, "-e", entity]
        agent_process = subprocess.Popen(agent_cmd)

        # Start run
        queued_run = launch_add(
            job=f"{entity}/{project}/{job_name}", queue_name=queue, entity=entity
        )

        # Assert successful
        run = queued_run.wait_until_finished()
        assert run.state == "finished"
    finally:
        agent_process.kill()
        subprocess.Popen(["rm", "-r", "artifacts"]).wait()


def test_agent_run_in_cluster():
    entity = "launch-release-testing"
    project = "release-testing"
    queue = "kubernetes-queue"
    job_name = (
        "job-305054156030.dkr.ecr.us-east-2.amazonaws.com_release-testing_latest:v0"
    )
    # api = client.CoreV1Api()
    # md = client.V1ObjectMeta(name="wandb")
    # ns = client.V1Namespace(metadata=md)
    # resp = api.create_namespace(ns)
    # pprint(resp)

    # Create an agent using EKS

    subprocess.Popen(["kubectl", "create", "namespace", "wandb"]).wait()

    # get user's wandb API key and AWS creds
    wandb_api_key = get_wandb_api_key()
    aws_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_token = os.getenv("AWS_SESSION_TOKEN")
    secrets = [
        ("wandb-api-key", wandb_api_key),
        ("aws-access-key-id", aws_id),
        ("aws-secret-access-key", aws_secret),
        ("aws-session-token", aws_token),
    ]
    for key, password in secrets:
        subprocess.Popen(
            [
                "kubectl",
                "-n",
                "wandb",
                "create",
                "secret",
                "generic",
                key,
                f"--from-literal=password={password}",
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
            job=f"{entity}/{project}/{job_name}",
            queue_name=queue,
            entity=entity,
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
