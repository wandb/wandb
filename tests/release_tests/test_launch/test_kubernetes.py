import pytest
import yaml
from utils import (
    cleanup_deployment,
    run_cmd,
    run_cmd_async,
    setup_cleanup_on_exit,
    update_dict,
    wait_for_image_job_completion,
)
from wandb.sdk.launch.launch_add import launch_add

NAMESPACE = "wandb-release-testing"
ENTITY = "launch-release-testing"
PROJECT = "release-testing"
QUEUE = "kubernetes-queue"
JOB_NAME = "sample_job:v0"  # simple job that counts to 50

LAUNCH_JOB_CONFIG = {
    "resource_args": {"kubernetes": {"namespace": NAMESPACE}},
}


@pytest.mark.timeout(180)
def test_kubernetes_agent_on_local_process():
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


def _create_config_files():
    """Create a launch-config.yml and launch-agent.yml."""
    launch_config = yaml.load_all(
        open("wandb/sdk/launch/deploys/kubernetes/launch-config.yaml")
    )
    launch_config_patch = yaml.load_all(
        open("tests/release_tests/test_launch/launch-config-patch.yaml")
    )
    final_launch_config = []
    for original, updated in zip(launch_config, launch_config_patch):
        document = dict(original)
        update_dict(document, dict(updated))
        final_launch_config.append(document)
    yaml.dump_all(
        final_launch_config,
        open("tests/release_tests/test_launch/launch-config.yml", "w+"),
    )
    launch_agent = yaml.load(
        open("wandb/sdk/launch/deploys/kubernetes/launch-agent.yaml")
    )
    launch_agent_patch = yaml.load(
        open("tests/release_tests/test_launch/launch-agent-patch.yaml")
    )
    launch_agent_dict = dict(launch_agent)
    update_dict(launch_agent_dict, dict(launch_agent_patch))
    yaml.dump(
        launch_agent_dict,
        open("tests/release_tests/test_launch/launch-agent.yml", "w+"),
    )


@pytest.mark.timeout(180)
def test_kubernetes_agent_in_cluster():
    _create_config_files()

    run_cmd(
        "python tools/build_launch_agent.py --tag wandb-launch-agent:release-testing"
    )
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
