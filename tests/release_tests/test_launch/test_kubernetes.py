import os
import signal
import sys
from typing import Optional, Tuple

import pytest
from kubernetes import client, config, watch
from utils import get_wandb_api_key, run_cmd, run_cmd_async
from wandb.sdk.launch.launch_add import launch_add

NAMESPACE = "wandb-release-testing"

CONFIG = {
    "resource_args": {
        "kubernetes": {
            "namespace": NAMESPACE,
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "env": [
                                    {
                                        "name": "WANDB_API_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "wandb-api-key",
                                                "key": "password",
                                            }
                                        },
                                    },
                                    {
                                        "name": "AWS_ACCESS_KEY_ID",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "aws-access-key-id",
                                                "key": "password",
                                            }
                                        },
                                    },
                                    {
                                        "name": "AWS_SECRET_ACCESS_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "aws-secret-access-key",
                                                "key": "password",
                                            }
                                        },
                                    },
                                    {
                                        "name": "AWS_SESSION_TOKEN",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "aws-session-token",
                                                "key": "password",
                                            }
                                        },
                                    },
                                ]
                            }
                        ]
                    }
                }
            },
        }
    },
}


def test_kubernetes_agent_on_local_process():
    entity = "launch-release-testing"
    project = "release-testing"
    queue = "kubernetes-queue"
    job_name = "job-source-release-testing-train.py:v1"

    try:
        # Start launch agent
        agent_process = run_cmd_async(f"wandb launch-agent -q {queue} -e {entity}")

        # Start run
        queued_run = launch_add(
            job=f"{entity}/{project}/{job_name}", queue_name=queue, entity=entity
        )

        # Assert successful
        run = queued_run.wait_until_finished()
        assert run.state == "finished"
    finally:
        agent_process.kill()
        run_cmd("rm -r artifacts")


@pytest.mark.timeout(180)
def test_kubernetes_agent_in_cluster(api_key, base_url):
    entity = "launch-release-testing"
    project = "release-testing"
    queue = "kubernetes-queue"
    job_name = (
        "job-305054156030.dkr.ecr.us-east-2.amazonaws.com_release-testing_latest:v0"
    )

    # get user's wandb API key and AWS creds
    if not api_key:
        api_key = get_wandb_api_key(base_url)
    aws_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_token = os.getenv("AWS_SESSION_TOKEN")
    _create_wandb_and_aws_secrets(api_key, aws_id, aws_secret, aws_token)

    run_cmd("kubectl apply -f tests/release_tests/test_launch/launch-config.yml")
    run_cmd("kubectl apply -f tests/release_tests/test_launch/launch-agent.yml")

    # Capture sigint so cleanup occurs even on ctrl-C
    sigint = signal.getsignal(signal.SIGINT)

    def cleanup(signum, frame):
        signal.signal(signal.SIGINT, sigint)
        _cleanup_deployment()
        sys.exit(1)

    signal.signal(signal.SIGINT, cleanup)

    pod_name = None
    try:
        # Start run
        launch_add(
            job=f"{entity}/{project}/{job_name}",
            queue_name=queue,
            entity=entity,
            config=CONFIG,
        )

        # Wait to finish. Can't use W&B wait_until_finished() because it's an image-based job
        pod_name, status = _wait_for_job_completion(entity, project)

        assert (
            status == "Succeeded"
        ), "Kubernetes job didn't succeed. Check Kubernetes pods and Docker container output."
    finally:
        # Cleanup
        _cleanup_deployment(pod_name)


def _cleanup_deployment(pod_name: Optional[str] = None):
    run_cmd(f"kubectl -n {NAMESPACE} delete deploy launch-agent-release-testing")
    if pod_name:
        run_cmd(f"kubectl -n {NAMESPACE} delete pod {pod_name}")


def _create_wandb_and_aws_secrets(
    wandb_api_key: str,
    aws_id: str,
    aws_secret: str,
    aws_token: str,
) -> None:
    run_cmd(f"kubectl create namespace {NAMESPACE}")
    secrets = [
        ("wandb-api-key", wandb_api_key),
        ("aws-access-key-id", aws_id),
        ("aws-secret-access-key", aws_secret),
        ("aws-session-token", aws_token),
    ]
    for key, password in secrets:
        # Delete if already existing
        run_cmd(
            f"kubectl -n {NAMESPACE} delete secret generic {key} --ignore-not-found"
        )
        run_cmd(
            f"kubectl -n {NAMESPACE} create secret generic {key} --from-literal=password={password}"
        )


def _wait_for_job_completion(entity: str, project: str) -> Tuple[str, str]:
    config.load_kube_config()
    v1 = client.CoreV1Api()
    w = watch.Watch()
    status = None
    pod_name = None
    for event in w.stream(
        v1.list_namespaced_pod, namespace=NAMESPACE, timeout_seconds=300
    ):
        if event["object"].metadata.name.startswith(f"launch-{entity}-{project}-"):
            pod_name = event["object"].metadata.name
            status = event["object"].status.phase
            if status == "Succeeded":
                w.stop()
    return pod_name, status
