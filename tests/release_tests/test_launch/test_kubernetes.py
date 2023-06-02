import os
import signal
import subprocess
import sys

from kubernetes import client, config, watch
from wandb.sdk.launch.launch_add import launch_add
from utils import get_wandb_api_key


def _create_wandb_and_aws_secrets(aws_id, aws_secret, aws_token, namespace):
    wandb_api_key = get_wandb_api_key()
    secrets = [
        ("wandb-api-key", wandb_api_key),
        ("aws-access-key-id", aws_id),
        ("aws-secret-access-key", aws_secret),
        ("aws-session-token", aws_token),
    ]
    for key, password in secrets:
        # Delete if already existing
        subprocess.Popen(
            [
                "kubectl",
                "-n",
                namespace,
                "delete",
                "secret",
                "generic",
                key,
                "--ignore-not-found",
            ]
        ).wait()
        subprocess.Popen(
            [
                "kubectl",
                "-n",
                namespace,
                "create",
                "secret",
                "generic",
                key,
                f"--from-literal=password={password}",
            ]
        ).wait()


def _wait_for_job_completion(entity, project):
    config.load_kube_config()
    v1 = client.CoreV1Api()
    w = watch.Watch()
    status = None
    pod_name = None
    for event in w.stream(
        v1.list_namespaced_pod, namespace="wandb", timeout_seconds=60
    ):
        if event["object"].metadata.name.startswith(f"launch-{entity}-{project}-"):
            pod_name = event["object"].metadata.name
            status = event["object"].status.phase
            if status == "Succeeded":
                w.stop()
    return pod_name, status


def test_kubernetes_agent_on_local_process():
    entity = "launch-release-testing"
    project = "release-testing"
    queue = "kubernetes-queue"
    job_name = "job-source-release-testing-train.py:v1"

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


def test_kubernetes_agent_in_cluster():
    entity = "launch-release-testing"
    project = "release-testing"
    queue = "kubernetes-queue"
    job_name = (
        "job-305054156030.dkr.ecr.us-east-2.amazonaws.com_release-testing_latest:v0"
    )

    # get user's wandb API key and AWS creds
    aws_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_token = os.getenv("AWS_SESSION_TOKEN")
    _create_wandb_and_aws_secrets(aws_id, aws_secret, aws_token, "wandb")

    subprocess.Popen(
        ["kubectl", "apply", "-f", "tests/release_tests/test_launch/launch-config.yml"]
    ).wait()
    subprocess.Popen(
        ["kubectl", "apply", "-f", "tests/release_tests/test_launch/launch-agent.yml"]
    ).wait()

    # Capture sigint so cleanup occurs even on ctrl-C
    sigint = signal.getsignal(signal.SIGINT)

    def cleanup(signum, frame):
        signal.signal(signal.SIGINT, sigint)
        subprocess.Popen(
            [
                "kubectl",
                "-n",
                "wandb",
                "delete",
                "deploy",
                "launch-agent-release-testing",
            ]
        ).wait()
        sys.exit(1)

    signal.signal(signal.SIGINT, cleanup)

    try:
        # Start run
        cfg = {"resource_args": {"kubernetes": {"namespace": "wandb"}}}
        launch_add(
            job=f"{entity}/{project}/{job_name}",
            queue_name=queue,
            entity=entity,
            config=cfg,
        )

        # Wait to finish. Can't use W&B wait_until_finished() because it's an image-based job
        pod_name, status = _wait_for_job_completion(entity, project)

        assert (
            status == "Succeeded"
        ), "Kubernetes job didn't succeed. Check Kubernetes pods and Docker container output."
    finally:
        # Cleanup
        subprocess.Popen(
            [
                "kubectl",
                "-n",
                "wandb",
                "delete",
                "deploy",
                "launch-agent-release-testing",
            ]
        ).wait()
        if pod_name:
            subprocess.Popen(
                [
                    "kubectl",
                    "-n",
                    "wandb",
                    "delete",
                    "pod",
                    pod_name,
                ]
            ).wait()
