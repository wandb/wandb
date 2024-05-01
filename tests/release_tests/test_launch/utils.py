import signal
import subprocess
import sys
from time import sleep
from typing import Optional

import wandb
import yaml
from kubernetes import client, config, watch
from wandb.apis.public import Api


def run_cmd(command: str) -> None:
    subprocess.Popen(command.split(" ")).wait()


def run_cmd_async(command: str) -> subprocess.Popen:
    # Returns process. Terminate with process.kill()
    return subprocess.Popen(
        command.split(" "), stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )


def cleanup_deployment(namespace: str):
    """Delete a k8s deployment and all pods in the same namespace."""
    config.load_kube_config()
    apps_api = client.AppsV1Api()
    core_api = client.CoreV1Api()

    apps_api.delete_namespaced_deployment(
        name="launch-agent-release-testing", namespace=namespace
    )
    pods = core_api.list_namespaced_pod(namespace=namespace).items
    for pod in pods:
        core_api.delete_namespaced_pod(name=pod.metadata.name, namespace=namespace)


def wait_for_queued_image_job_completion(entity: str, project: str, queued_run) -> str:
    item = queued_run._get_item()
    tries = 0
    while not item["associatedRunId"] and tries < 5:
        sleep(2**tries)
        tries += 1
        item = queued_run._get_item()
    run_id = item["associatedRunId"]
    run = wait_for_run_completion(f"{entity}/{project}/{run_id}")
    return run


def wait_for_k8s_job_completion(
    namespace: str, entity: str, project: str, num_jobs: int
) -> str:
    """W&B's wait_until_finished() doesn't work for image based jobs, so poll the k8s output for job completion."""
    config.load_kube_config()
    v1 = client.CoreV1Api()
    w = watch.Watch()
    status = None
    completed_jobs = 0
    for event in w.stream(
        v1.list_namespaced_pod, namespace=namespace, timeout_seconds=300
    ):
        if event["object"].metadata.name.startswith(f"launch-{entity}-{project}-"):
            status = event["object"].status.phase
            if status == "Succeeded":
                completed_jobs += 1
            if completed_jobs == num_jobs:
                w.stop()
    return status


def wait_for_run_completion(path: str) -> "wandb.Run":
    api = Api()
    tries = 0
    run = None
    while not (run and run.state == "finished") and tries < 8:
        # Sometimes takes a bit for the run's completion to populate in W&B
        try:
            run = api.run(path=path)
            run.load(force=True)
        except wandb.errors.CommError:
            pass
        sleep(2**tries)
        tries += 1
    return run


def setup_cleanup_on_exit(namespace: str):
    # Capture sigint so cleanup occurs even on ctrl-C
    sigint = signal.getsignal(signal.SIGINT)

    def cleanup(signum, frame):
        signal.signal(signal.SIGINT, sigint)
        cleanup_deployment(namespace)
        sys.exit(1)

    signal.signal(signal.SIGINT, cleanup)


def update_dict(original, updated):
    """Recursively apply a patch dict to an original.

    Any item that's not a dict (list, str, etc) is copied over entirely and overwrites contents of original.
    """
    for key, value in updated.items():
        if isinstance(value, dict) and key in original:
            update_dict(original[key], value)
        else:
            original[key] = value


def create_config_files(api_key: str, agent_image: Optional[str]):
    """Create a launch-config.yml and launch-agent.yml."""
    launch_config = yaml.load_all(
        open("wandb/sdk/launch/deploys/kubernetes/launch-config.yaml"),
        Loader=yaml.Loader,
    )
    launch_config_patch = yaml.load_all(
        open("tests/release_tests/test_launch/launch-config-patch.yaml"),
        Loader=yaml.Loader,
    )
    final_launch_config = []
    for original, updated in zip(launch_config, launch_config_patch):
        document = dict(original)
        update_dict(document, dict(updated))
        final_launch_config.append(document)
    final_launch_config[-1]["stringData"]["password"] = api_key
    yaml.dump_all(
        final_launch_config,
        open("tests/release_tests/test_launch/launch-config.yml", "w+"),
    )
    launch_agent = yaml.load(
        open("wandb/sdk/launch/deploys/kubernetes/launch-agent.yaml"),
        Loader=yaml.Loader,
    )
    launch_agent_patch = dict(
        yaml.load(
            open("tests/release_tests/test_launch/launch-agent-patch.yaml"),
            Loader=yaml.Loader,
        )
    )
    if agent_image:
        launch_agent_patch["spec"]["template"]["spec"]["containers"][0]["image"] = (
            agent_image
        )
    launch_agent_dict = dict(launch_agent)
    update_dict(launch_agent_dict, launch_agent_patch)
    yaml.dump(
        launch_agent_dict,
        open("tests/release_tests/test_launch/launch-agent.yml", "w+"),
    )


def init_agent_in_launch_cluster(
    namespace: str, api_key: str, agent_image: Optional[str]
):
    """Deploy the agent in provided cluster namespace."""
    create_config_files(api_key, agent_image)
    run_cmd("kubectl apply -f tests/release_tests/test_launch/launch-config.yml")
    run_cmd("kubectl apply -f tests/release_tests/test_launch/launch-agent.yml")
    setup_cleanup_on_exit(namespace)


def get_sweep_id_from_proc(proc: subprocess.Popen) -> Optional[str]:
    while True:
        output = proc.stdout.readline().decode()
        if "Created sweep with ID: " in output:
            sweep_id = output.split("ID: ")[1].rstrip()
            return sweep_id
        if proc.poll() is not None:
            break
    return None
