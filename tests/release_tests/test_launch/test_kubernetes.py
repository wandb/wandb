import os
import signal
import subprocess
import sys
from typing import Optional, Tuple

from kubernetes import client, config, watch
from utils import get_wandb_api_key
from wandb.sdk.launch.launch_add import launch_add


def _create_wandb_and_aws_secrets(
    wandb_api_key: Optional[str],
    aws_id: str,
    aws_secret: str,
    aws_token: str,
    namespace: str,
) -> None:
    if not wandb_api_key:
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


def _wait_for_job_completion(entity: str, project: str) -> Tuple[str, str]:
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


def test_kubernetes_agent_in_cluster(api_key):
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

    # TODO
    # helm repo add wandb https://wandb.github.io/helm-charts
    # note: LICENSE=eyJhbGciOiJSUzI1NiIsImtpZCI6InUzaHgyQjQyQWhEUXM1M0xQY09yNnZhaTdoSlduYnF1bTRZTlZWd1VwSWM9In0.eyJjb25jdXJyZW50QWdlbnRzIjoxLCJ0cmlhbCI6ZmFsc2UsIm1heFN0b3JhZ2VHYiI6MTAsIm1heFRlYW1zIjowLCJtYXhVc2VycyI6MSwibWF4Vmlld09ubHlVc2VycyI6MCwibWF4UmVnaXN0ZXJlZE1vZGVscyI6MiwiZXhwaXJlc0F0IjoiMjAyNC0wNi0wOVQyMzozMTo0MS4wMzFaIiwiZGVwbG95bWVudElkIjoiM2UzZGI0NTAtNzdlNC00NGE0LThiZTQtYjdjZjg2YTA5MjQ2IiwiZmxhZ3MiOltdLCJhY2Nlc3NLZXkiOiI5ZjExMGEyMy1kNjA4LTQyZmYtYWIxZC1mMzU3ZWFmYjdkNjYiLCJzZWF0cyI6MSwidmlld09ubHlTZWF0cyI6MCwidGVhbXMiOjAsInJlZ2lzdGVyZWRNb2RlbHMiOjIsInN0b3JhZ2VHaWdzIjoxMCwiZXhwIjoxNzE3OTc1OTAxfQ.jfWHTcLLcpgF_h7yCsEoZdipa9Q4XmzNiYwHajZExC6zh6zAp2cJJKk73sjBKTM_D4SU3qIHivIPZT-K6DrIbjpcAyOYF2VLbIW4rz7jht8kOLtPLfCuD312pwqtdL-8nbSsFgNQM9eeon6-CKwHxuhC9W9j2cReWLAln56ovdN09kcAuVZkCz6YyZqKAP6nEN3Ul9YtLMyAfHE-A2e2KPBTTPNm6fIhihMwgxAqFNa33aYHPScOVHhfZfJgL8QwOZKIa3DYHp9VTSdqohx1YUZTctVv6avSTNJ5pbkWdOehjmbDWWN1i8M2JOxPmfdBVJRespcEHb29ne_HYB2I_A
    # license is needed for helm download

    # subprocess.Popen(
    #     ["kubectl", "apply", "-f", "tests/release_tests/test_launch/launch-config.yml"]
    # ).wait()
    # subprocess.Popen(
    #     ["kubectl", "apply", "-f", "tests/release_tests/test_launch/launch-agent.yml"]
    # ).wait()

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
