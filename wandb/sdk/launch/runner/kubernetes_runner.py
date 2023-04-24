import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.registry.local_registry import LocalRegistry
from wandb.util import get_module

from .._project_spec import EntryPoint, LaunchProject
from ..builder.build import get_env_vars_dict
from ..utils import (
    LOG_PREFIX,
    PROJECT_SYNCHRONOUS,
    LaunchError,
    get_kube_context_and_api_client,
    make_name_dns_safe,
)
from .abstract import AbstractRun, AbstractRunner, Status

get_module(
    "kubernetes",
    required="Kubernetes runner requires the kubernetes package. Please install it with `pip install wandb[launch]`.",
)

from kubernetes import client  # type: ignore # noqa: E402
from kubernetes.client.api.batch_v1_api import BatchV1Api  # type: ignore # noqa: E402
from kubernetes.client.api.core_v1_api import CoreV1Api  # type: ignore # noqa: E402
from kubernetes.client.models.v1_job import V1Job  # type: ignore # noqa: E402
from kubernetes.client.models.v1_secret import V1Secret  # type: ignore # noqa: E402

TIMEOUT = 5
MAX_KUBERNETES_RETRIES = (
    60  # default 10 second loop time on the agent, this is 10 minutes
)
FAIL_MESSAGE_INTERVAL = 60

_logger = logging.getLogger(__name__)


class KubernetesSubmittedRun(AbstractRun):
    def __init__(
        self,
        batch_api: "BatchV1Api",
        core_api: "CoreV1Api",
        name: str,
        pod_names: List[str],
        namespace: Optional[str] = "default",
        secret: Optional["V1Secret"] = None,
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
        self.secret = secret

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
            wandb.termlog(f"{LOG_PREFIX}Job {self.name} status: {status}")
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

        pod = self.core_api.read_namespaced_pod(
            name=self.pod_names[0], namespace=self.namespace
        )
        if pod.status.phase in ["Pending", "Unknown"]:
            now = time.time()
            if self._fail_count == 0:
                self._fail_first_msg_time = now
                self._fail_last_msg_time = 0.0
            self._fail_count += 1
            if now - self._fail_last_msg_time > FAIL_MESSAGE_INTERVAL:
                wandb.termlog(
                    f"{LOG_PREFIX}Pod has not started yet for job: {self.name}. Will wait up to {round(10 - (now - self._fail_first_msg_time)/60)} minutes."
                )
                self._fail_last_msg_time = now
            if self._fail_count > MAX_KUBERNETES_RETRIES:
                raise LaunchError(f"Failed to start job {self.name}")
        # todo: we only handle the 1 pod case. see https://kubernetes.io/docs/concepts/workloads/controllers/job/#parallel-jobs for multipod handling
        return_status = None
        if status.succeeded == 1:
            return_status = Status("finished")
        elif status.failed is not None and status.failed >= 1:
            return_status = Status("failed")
        elif status.active == 1:
            return Status("running")
        elif status.conditions is not None and status.conditions[0].type == "Suspended":
            return_status = Status("stopped")
        else:
            return_status = Status("unknown")
        if (
            return_status.state in ["stopped", "failed", "finished"]
            and self.secret is not None
        ):
            try:
                self.core_api.delete_namespaced_secret(
                    self.secret.metadata.name, self.namespace
                )
            except Exception as e:
                wandb.termerror(
                    f"Error deleting secret {self.secret.metadata.name}: {str(e)}"
                )
        return return_status

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
    def __init__(
        self, api: Api, backend_config: Dict[str, Any], environment: AbstractEnvironment
    ) -> None:
        super().__init__(api, backend_config)
        self.environment = environment

    def wait_job_launch(
        self, job_name: str, namespace: str, core_api: "CoreV1Api"
    ) -> List[str]:
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
            f"{LOG_PREFIX}Job {job_name} created on pod(s) {', '.join(pod_names)}. See logs with e.g. `kubectl logs {pod_names[0]} -n {namespace}`."
        )
        return pod_names

    def get_namespace(
        self, resource_args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        default_namespace = (
            context["context"].get("namespace", "default") if context else "default"
        )
        return (  # type: ignore[no-any-return]
            self.backend_config.get("runner", {}).get("namespace")
            or resource_args.get("namespace")
            or default_namespace
        )

    def _inject_defaults(
        self,
        resource_args: Dict[str, Any],
        launch_project: LaunchProject,
        builder: Optional[AbstractBuilder],
        namespace: str,
        core_api: "CoreV1Api",
    ) -> Tuple[Dict[str, Any], Optional["V1Secret"]]:
        """Apply our default values, return job dict and secret."""
        job: Dict[str, Any] = {
            "apiVersion": "batch/v1",
            "kind": "Job",
        }
        job.update(resource_args)

        job_metadata: Dict[str, Any] = job.get("metadata", {})
        job_spec: Dict[str, Any] = {"backoffLimit": 0, "ttlSecondsAfterFinished": 60}
        job_spec.update(job.get("spec", {}))
        pod_template: Dict[str, Any] = job_spec.get("template", {})
        pod_spec: Dict[str, Any] = {"restartPolicy": "Never"}
        pod_spec.update(pod_template.get("spec", {}))
        containers: List[Dict[str, Any]] = pod_spec.get("containers", [{}])

        # name precedence: name in spec > generated name
        if not job_metadata.get("name"):
            job_metadata["generateName"] = make_name_dns_safe(
                f"launch-{launch_project.target_entity}-{launch_project.target_project}-"
            )

        for i, cont in enumerate(containers):
            if "name" not in cont:
                cont["name"] = cont.get("name", "launch" + str(i))
            if "securityContext" not in cont:
                cont["securityContext"] = {
                    "allowPrivilegeEscalation": False,
                    "capabilities": {"drop": ["ALL"]},
                    "seccompProfile": {"type": "RuntimeDefault"},
                }

        secret = None
        entry_point = launch_project.get_single_entry_point()
        if launch_project.docker_image:
            if len(containers) > 1:
                raise LaunchError(
                    "Invalid specification of multiple containers. See https://docs.wandb.ai/guides/launch for guidance on submitting jobs."
                )
            # dont specify run id if user provided image, could have multiple runs
            containers[0]["image"] = launch_project.docker_image
            # TODO: handle secret pulling image from registry
        elif not any(["image" in cont for cont in containers]):
            if len(containers) > 1:
                raise LaunchError(
                    "Launch only builds one container at a time. See https://docs.wandb.ai/guides/launch for guidance on submitting jobs."
                )
            assert entry_point is not None
            assert builder is not None
            image_uri = builder.build_image(launch_project, entry_point)
            # in the non instance case we need to make an imagePullSecret
            # so the new job can pull the image
            if not builder.registry:
                raise LaunchError(
                    "No registry specified. Please specify a registry in your wandb/settings file or pass a registry to the builder."
                )
            secret = maybe_create_imagepull_secret(
                core_api, builder.registry, launch_project.run_id, namespace
            )
            if secret is not None:
                pod_spec["imagePullSecrets"] = [
                    {"name": f"regcred-{launch_project.run_id}"}
                ]

            containers[0]["image"] = image_uri

        inject_entrypoint_and_args(
            containers,
            entry_point,
            launch_project.override_args,
            launch_project.override_entrypoint is not None,
        )

        env_vars = get_env_vars_dict(launch_project, self._api)
        for cont in containers:
            # Add our env vars to user supplied env vars
            env = cont.get("env", [])
            env.extend(
                [{"name": key, "value": value} for key, value in env_vars.items()]
            )
            cont["env"] = env

        pod_spec["containers"] = containers
        pod_template["spec"] = pod_spec
        job_spec["template"] = pod_template
        job["spec"] = job_spec
        job["metadata"] = job_metadata

        return job, secret

    def run(
        self,
        launch_project: LaunchProject,
        builder: Optional[AbstractBuilder],
    ) -> Optional[AbstractRun]:  # noqa: C901
        kubernetes = get_module(  # noqa: F811
            "kubernetes",
            required="Kubernetes runner requires the kubernetes package. Please"
            " install it with `pip install wandb[launch]`.",
        )
        resource_args = launch_project.resource_args.get("kubernetes", {})
        if not resource_args:
            wandb.termlog(
                f"{LOG_PREFIX}Note: no resource args specified. Add a Kubernetes yaml spec or other options in a json file with --resource-args <json>."
            )
        _logger.info(f"Running Kubernetes job with resource args: {resource_args}")

        context, api_client = get_kube_context_and_api_client(kubernetes, resource_args)

        batch_api = kubernetes.client.BatchV1Api(api_client)
        core_api = kubernetes.client.CoreV1Api(api_client)

        namespace = self.get_namespace(resource_args, context)

        job, secret = self._inject_defaults(
            resource_args,
            launch_project,
            builder,
            namespace,
            core_api,
        )

        msg = "Creating Kubernetes job"
        if "name" in resource_args:
            msg += f": {resource_args['name']}"
        _logger.info(msg)
        job_response = kubernetes.utils.create_from_yaml(
            api_client, yaml_objects=[job], namespace=namespace
        )[0][
            0
        ]  # create_from_yaml returns a nested list of k8s objects
        job_name = job_response.metadata.name

        pod_names = self.wait_job_launch(job_name, namespace, core_api)

        submitted_job = KubernetesSubmittedRun(
            batch_api, core_api, job_name, pod_names, namespace, secret
        )

        if self.backend_config[PROJECT_SYNCHRONOUS]:
            submitted_job.wait()

        return submitted_job


def inject_entrypoint_and_args(
    containers: List[dict],
    entry_point: Optional[EntryPoint],
    override_args: List[str],
    should_override_entrypoint: bool,
) -> None:
    for i in range(len(containers)):
        if override_args:
            containers[i]["args"] = override_args
        if entry_point and (
            not containers[i].get("command") or should_override_entrypoint
        ):
            containers[i]["command"] = entry_point.command


def maybe_create_imagepull_secret(
    core_api: "CoreV1Api",
    registry: AbstractRegistry,
    run_id: str,
    namespace: str,
) -> Optional["V1Secret"]:
    secret = None
    if isinstance(registry, LocalRegistry):
        # Secret not required
        return None
    uname, token = registry.get_username_password()
    creds_info = {
        "auths": {
            registry.uri: {
                "auth": base64.b64encode(f"{uname}:{token}".encode()).decode(),
                # need an email but the use is deprecated
                "email": "deprecated@wandblaunch.com",
            }
        }
    }
    secret_data = {
        ".dockerconfigjson": base64.b64encode(json.dumps(creds_info).encode()).decode()
    }
    secret = client.V1Secret(
        data=secret_data,
        metadata=client.V1ObjectMeta(name=f"regcred-{run_id}", namespace=namespace),
        kind="Secret",
        type="kubernetes.io/dockerconfigjson",
    )
    try:
        return core_api.create_namespaced_secret(namespace, secret)
    except Exception as e:
        raise LaunchError(f"Exception when creating Kubernetes secret: {str(e)}\n")
