import os
import time
from typing import Any, Dict, List, Optional

if False:
    import kubernetes  # type: ignore  # noqa: F401
    from kubernetes.client.api.batch_v1_api import BatchV1Api  # type: ignore
    from kubernetes.client.api.core_v1_api import CoreV1Api  # type: ignore
    from kubernetes.client.models.v1_job import V1Job  # type: ignore
import wandb
import wandb.docker as docker
from wandb.errors import LaunchError
from wandb.util import get_module, load_json_yaml_dict

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import get_entry_point_command, LaunchProject
from ..docker import (
    construct_local_image_uri,
    generate_docker_image,
    get_env_vars_dict,
)
from ..utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)

TIMEOUT = 5
MAX_KUBERNETES_RETRIES = (
    60  # default 10 second loop time on the agent, this is 10 minutes
)


class KubernetesSubmittedRun(AbstractRun):
    def __init__(
        self,
        batch_api: "BatchV1Api",
        core_api: "CoreV1Api",
        name: str,
        pod_names: List[str],
        namespace: Optional[str] = "default",
    ) -> None:
        self.batch_api = batch_api
        self.core_api = core_api
        self.name = name
        self.namespace = namespace
        self.job = self.batch_api.read_namespaced_job(
            name=self.name, namespace=self.namespace
        )
        self._fail_count = 0
        self.pod_names = pod_names

    @property
    def id(self) -> str:
        return self.name

    def get_job(self) -> "V1Job":
        return self.batch_api.read_namespaced_job(
            name=self.name, namespace=self.namespace
        )

    def wait(self) -> bool:
        while True:
            status = self.get_status()
            wandb.termlog(f"Job {self.name} status: {status}")
            if status.state != "running":
                break
            time.sleep(5)
        return (
            status.state == "finished"
        )  # todo: not sure if this (copied from aws runner) is the right approach? should we return false on failure

    def get_status(self) -> Status:
        job_response = self.batch_api.read_namespaced_job_status(
            name=self.name, namespace=self.namespace
        )
        status = job_response.status
        try:
            self.core_api.read_namespaced_pod_log(
                name=self.pod_names[0], namespace=self.namespace
            )
        except Exception as e:
            self._fail_count += 1
            if self._fail_count == 1:
                wandb.termlog(
                    "Failed to get pod status for job: {}. Will wait up to 10 minutes for job to start.".format(
                        self.name
                    )
                )
            if self._fail_count > MAX_KUBERNETES_RETRIES:
                raise LaunchError(
                    f"Failed to start job {self.name}, because of error {str(e)}"
                )

        # todo: we only handle the 1 pod case. see https://kubernetes.io/docs/concepts/workloads/controllers/job/#parallel-jobs for multipod handling
        if status.succeeded == 1:
            return Status("finished")
        elif status.failed is not None and status.failed >= 1:
            return Status("failed")
        elif status.active == 1:
            return Status("running")
        if status.conditions is not None and status.conditions[0].type == "Suspended":
            return Status("stopped")
        return Status("unknown")

    def suspend(self) -> None:
        self.job.spec.suspend = True
        self.batch_api.patch_namespaced_job(
            name=self.name, namespace=self.namespace, body=self.job
        )
        timeout = TIMEOUT
        job_response = self.batch_api.read_namespaced_job_status(
            name=self.name, namespace=self.namespace
        )
        while job_response.status.conditions is None and timeout > 0:
            time.sleep(1)
            timeout -= 1
            job_response = self.batch_api.read_namespaced_job_status(
                name=self.name, namespace=self.namespace
            )

        if timeout == 0 or job_response.status.conditions[0].type != "Suspended":
            raise LaunchError(
                "Failed to suspend job {}. Check Kubernetes dashboard for more info.".format(
                    self.name
                )
            )

    def cancel(self) -> None:
        self.suspend()
        self.batch_api.delete_namespaced_job(name=self.name, namespace=self.namespace)


class KubernetesRunner(AbstractRunner):
    def _set_context(
        self,
        kubernetes: Any,  # noqa: F811
        config_file: str,
        resource_args: Dict[str, Any],  # noqa: F811
    ) -> Any:
        all_contexts, active_context = kubernetes.config.list_kube_config_contexts(
            config_file
        )
        if resource_args.get("context"):
            context_name = resource_args["context"]
            for c in all_contexts:
                if c["name"] == context_name:
                    return c
            raise LaunchError(f"Specified context {context_name} was not found.")
        else:
            return active_context

    def run(self, launch_project: LaunchProject) -> Optional[AbstractRun]:  # noqa: C901
        kubernetes = get_module(  # noqa: F811
            "kubernetes", "KubernetesRunner requires kubernetes to be installed"
        )

        resource_args = launch_project.resource_args.get("kubernetes", {})
        if not resource_args:
            wandb.termlog(
                "Note: no resource args specified. Add a Kubernetes yaml spec or other options in a json file with --resource-args <json>."
            )

        config_file = resource_args.get("config_file", None)
        context = None
        if config_file is not None or os.path.exists(
            os.path.expanduser("~/.kube/config")
        ):
            # context only exist in the non-incluster case
            context = self._set_context(kubernetes, config_file, resource_args)
            # if config_file is None then loads default in ~/.kube
            kubernetes.config.load_kube_config(config_file, context["name"])
            api_client = kubernetes.config.new_client_from_config(
                config_file, context=context["name"]
            )
        else:
            # attempt to load cluster config
            kubernetes.config.load_incluster_config()
            api_client = kubernetes.client.api_client.ApiClient()

        batch_api = kubernetes.client.BatchV1Api(api_client)
        core_api = kubernetes.client.CoreV1Api(api_client)

        # allow users to specify template or entire spec
        if resource_args.get("job_spec"):
            job_dict = load_json_yaml_dict(resource_args["job_spec"])
        else:
            # begin constructing job sped
            job_dict = {"apiVersion": "batch/v1", "kind": "Job"}

        # extract job spec component parts for convenience
        job_metadata = job_dict.get("metadata", {})
        job_spec = job_dict.get("spec", {})
        pod_template = job_spec.get("template", {})
        pod_metadata = pod_template.get("metadata", {})
        pod_spec = pod_template.get("spec", {})
        containers = pod_spec.get("containers", [{}])
        job_status = job_dict.get("status", {})

        # begin pulling resource arg overrides. all of these are optional

        # allow top-level namespace override, otherwise take namespace specified at the job level, or default in current context
        default = (
            context["context"].get("namespace", "default") if context else "default"
        )
        namespace = resource_args.get(
            "namespace",
            job_metadata.get("namespace", default),
        )

        # name precedence: resource args override > name in spec file > generated name
        job_metadata["name"] = resource_args.get("job_name", job_metadata.get("name"))
        if not job_metadata.get("name"):
            job_metadata["generateName"] = "launch-"

        if resource_args.get("job_labels"):
            job_metadata["labels"] = resource_args.get("job_labels")

        if resource_args.get("backoff_limit"):
            job_spec["backoffLimit"] = resource_args.get("backoff_limit")
        if resource_args.get("completions"):
            job_spec["completions"] = resource_args.get("completions")
        if resource_args.get("parallelism"):
            job_spec["parallelism"] = resource_args.get("parallelism")
        if resource_args.get("suspend"):
            job_spec["suspend"] = resource_args.get("suspend")

        pod_spec["restartPolicy"] = resource_args.get("restart_policy", "Never")
        if resource_args.get("preemption_policy"):
            pod_spec["preemptionPolicy"] = resource_args.get("preemption_policy")
        if resource_args.get("node_name"):
            pod_spec["nodeName"] = resource_args.get("node_name")
        if resource_args.get("node_selectors"):
            pod_spec["nodeSelectors"] = resource_args.get("node_selectors")

        if resource_args.get("container_name"):
            if len(containers) > 1:
                raise LaunchError(
                    "Container name override not supported for multiple containers. Specify in yaml file supplied via job_spec."
                )
            containers[0]["name"] = resource_args["container_name"]
        else:
            for i, cont in enumerate(containers):
                cont["name"] = cont.get("name", "launch" + str(i))
        multi_container_override = len(containers) > 1
        for cont in containers:
            container_resources = cont.get("resources", {})
            if resource_args.get("resource_requests"):
                container_resources["requests"] = resource_args.get("resource_requests")
            if resource_args.get("resource_limits"):
                container_resources["limits"] = resource_args.get("resource_limits")
            if container_resources:
                multi_container_override &= (
                    cont.get("resources") != container_resources
                )  # if multiple containers and we changed something
                cont["resources"] = container_resources
            cont["security_context"] = {
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
                "seccompProfile": {"type": "RuntimeDefault"},
            }
        if multi_container_override:
            wandb.termwarn(
                "Container overrides (e.g. resource limits) were provided with multiple containers specified: overrides will be applied to all containers."
            )

        # env vars
        env_vars = get_env_vars_dict(launch_project, self._api)

        # cmd
        entry_point = launch_project.get_single_entry_point()
        docker_args: Dict[str, Any] = self.backend_config[PROJECT_DOCKER_ARGS]
        if docker_args and list(docker_args) != ["docker_image"]:
            wandb.termwarn(
                "Docker args are not supported for Kubernetes. Not using docker args"
            )
        entry_cmd = get_entry_point_command(
            entry_point, launch_project.override_args
        ).split()
        if entry_cmd:
            # if user hardcodes cmd into their image, we don't need to run on top of that
            for cont in containers:
                cont["command"] = entry_cmd

        if launch_project.docker_image:
            if len(containers) > 1:
                raise LaunchError(
                    "Multiple container configurations should be specified in a yaml file supplied via job_spec."
                )
            # dont specify run id if user provided image, could have multiple runs
            env_vars.pop("WANDB_RUN_ID")
            containers[0]["image"] = launch_project.docker_image
        elif any(["image" in cont for cont in containers]):
            # user specified image configurations via kubernetes yaml, could have multiple images
            # dont specify run id if user provided image, could have multiple runs
            env_vars.pop("WANDB_RUN_ID")
        else:
            if len(containers) > 1:
                raise LaunchError(
                    "Launch only builds one container at a time. Multiple container configurations should be pre-built and specified in a yaml file supplied via job_spec."
                )
            registry = resource_args.get("registry")
            if registry is None:
                # allow local registry usage for eg local clusters but throw a warning
                wandb.termlog(
                    "Warning: No Docker registry specified. Image will be hosted on local registry, which may not be accessible to your training cluster."
                )

            image_uri = construct_local_image_uri(launch_project)
            if registry:
                image_uri = os.path.join(registry, image_uri)
            generate_docker_image(
                launch_project,
                image_uri,
                entry_point,
                docker_args,
                runner_type="kubernetes",
            )
            containers[0]["image"] = image_uri
            if registry:
                repo, tag = image_uri.split(":")
                docker.push(repo, tag)

        # reassemble spec
        given_env_vars = resource_args.get("env", {})
        merged_env_vars = {**env_vars, **given_env_vars}
        for cont in containers:
            cont["env"] = [{"name": k, "value": v} for k, v in merged_env_vars.items()]
        pod_spec["containers"] = containers
        pod_template["spec"] = pod_spec
        pod_template["metadata"] = pod_metadata
        job_spec["template"] = pod_template
        job_dict["spec"] = job_spec
        job_dict["metadata"] = job_metadata
        job_dict["status"] = job_status

        if not self.ack_run_queue_item(launch_project):
            return None

        job_response = kubernetes.utils.create_from_yaml(
            api_client, yaml_objects=[job_dict], namespace=namespace
        )[0][
            0
        ]  # create_from_yaml returns a nested list of k8s objects
        job_name = job_response.metadata.labels["job-name"]

        pods = core_api.list_namespaced_pod(
            label_selector=f"job-name={job_name}", namespace=namespace
        )
        timeout = TIMEOUT
        while len(pods.items) == 0 and timeout > 0:
            time.sleep(1)
            timeout -= 1
            pods = core_api.list_namespaced_pod(
                label_selector=f"job-name={job_name}", namespace=namespace
            )

        if timeout == 0:
            raise LaunchError(
                "No pods found for job {}. Check dashboard to see if job was launched successfully.".format(
                    job_name
                )
            )

        pod_names = [pi.metadata.name for pi in pods.items]
        wandb.termlog(
            "Job {job} created on pod(s) {pod_names}. See logs with e.g. `kubectl logs {first_pod}`.".format(
                job=job_name, pod_names=", ".join(pod_names), first_pod=pod_names[0]
            )
        )

        submitted_job = KubernetesSubmittedRun(
            batch_api,
            core_api,
            job_name,
            pod_names,
            namespace,
        )

        if self.backend_config[PROJECT_SYNCHRONOUS]:
            submitted_job.wait()

        return submitted_job
