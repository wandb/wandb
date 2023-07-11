import os

import pytest
from utils import (
    cleanup_deployment,
    create_wandb_and_aws_secrets,
    get_wandb_api_key,
    run_cmd,
    run_cmd_async,
    setup_cleanup_on_exit,
    wait_for_image_job_completion,
)
from wandb.sdk.launch.launch_add import launch_add

NAMESPACE = "wandb-release-testing"
ENTITY = "launch-release-testing"
PROJECT = "release-testing"
QUEUE = "kubernetes-queue"
JOB_NAME = "sample_job:v0"  # simple job that counts to 50

LAUNCH_JOB_CONFIG = {
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


@pytest.mark.timeout(180)
def test_kubernetes_agent_on_local_process(api_key, base_url):
    if not api_key:
        api_key = get_wandb_api_key(base_url)
    aws_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_token = os.getenv("AWS_SESSION_TOKEN")

    create_wandb_and_aws_secrets(NAMESPACE, api_key, aws_id, aws_secret, aws_token)

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
            config=LAUNCH_JOB_CONFIG,
        )

        status, completed_run = wait_for_image_job_completion(
            NAMESPACE, ENTITY, PROJECT, queued_run
        )

        summary = completed_run.summary
        history = completed_run.history(pandas=False)

        assert (
            status == "Succeeded"
        ), "Kubernetes job didn't succeed. Check Kubernetes pods and Docker container output."
        assert summary["time_elapsed"]
        assert summary["avg"]
        assert len(history) == 50
        assert history[-1]["steps"] == 49
    finally:
        agent_process.kill()
        run_cmd("rm -r artifacts")


@pytest.mark.timeout(180)
def test_kubernetes_agent_in_cluster(api_key, base_url):
    # get user's wandb API key and AWS creds
    if not api_key:
        api_key = get_wandb_api_key(base_url)
    aws_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_token = os.getenv("AWS_SESSION_TOKEN")
    create_wandb_and_aws_secrets(NAMESPACE, api_key, aws_id, aws_secret, aws_token)

    run_cmd("kubectl apply -f tests/release_tests/test_launch/launch-config.yml")
    run_cmd("kubectl apply -f tests/release_tests/test_launch/launch-agent.yml")

    setup_cleanup_on_exit(NAMESPACE)

    try:
        # Start run
        queued_run = launch_add(
            job=f"{ENTITY}/{PROJECT}/{JOB_NAME}",
            queue_name=QUEUE,
            entity=ENTITY,
            config=LAUNCH_JOB_CONFIG,
        )

        status, completed_run = wait_for_image_job_completion(
            NAMESPACE, ENTITY, PROJECT, queued_run
        )

        summary = completed_run.summary
        history = completed_run.history(pandas=False)

        assert (
            status == "Succeeded"
        ), "Kubernetes job didn't succeed. Check Kubernetes pods and Docker container output."
        assert summary["time_elapsed"]
        assert summary["avg"]
        assert len(history) == 50
        assert history[-1]["steps"] == 49

    finally:
        # Cleanup
        cleanup_deployment(NAMESPACE)
