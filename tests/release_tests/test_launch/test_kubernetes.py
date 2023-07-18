import pytest
import yaml
from utils import (
    cleanup_deployment,
    get_sweep_id_from_proc,
    init_agent_in_launch_cluster,
    run_cmd,
    run_cmd_async,
    wait_for_image_job_completion,
    wait_for_run_completion,
)
from wandb.apis.public import Api, Sweep
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


@pytest.mark.timeout(180)
def test_kubernetes_agent_in_cluster():
    init_agent_in_launch_cluster(NAMESPACE)
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


@pytest.mark.timeout(360)
def test_kubernetes_agent_in_cluster_sweep():
    init_agent_in_launch_cluster(NAMESPACE)
    run_cap = 4
    try:
        sweep_config = {
            "job": f"{ENTITY}/{PROJECT}/{JOB_NAME}",
            "project": PROJECT,
            "entity": ENTITY,
            "run_cap": run_cap,
            "method": "bayes",
            "metric": {
                "name": "avg",
                "goal": "maximize",
            },
            "parameters": {
                "param1": {
                    "min": 0,
                    "max": 8,
                }
            },
        }

        yaml.dump(sweep_config, open("c.yml", "w"))

        proc = run_cmd_async(f"wandb launch-sweep c.yml -q {QUEUE}")

        # Poll process.stdout to show stdout live
        sweep_id = get_sweep_id_from_proc(proc)
        assert sweep_config

        # poll on sweep scheduler run
        run = wait_for_run_completion(f"{ENTITY}/{PROJECT}/{sweep_id}")
        assert run

        api = Api()
        sweep: Sweep = api.sweep(f"{ENTITY}/{PROJECT}/{sweep_id}")
        sweep.load(force=True)

        assert len(sweep.runs) == run_cap
        for run in sweep.runs:
            assert run["config"]["param1"] in list(range(0, 8 + 1))

    finally:
        cleanup_deployment(NAMESPACE)
