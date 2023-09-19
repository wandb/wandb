"""Implementation of KubernetesRunner class for wandb launch."""

import base64
import json
import logging
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import yaml

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.registry.azure_container_registry import AzureContainerRegistry
from wandb.sdk.launch.registry.local_registry import LocalRegistry
from wandb.sdk.launch.runner.abstract import Status
from wandb.util import get_module

from .._project_spec import EntryPoint, LaunchProject
from ..builder.build import get_env_vars_dict
from ..errors import LaunchError
from ..utils import (
    LOG_PREFIX,
    MAX_ENV_LENGTHS,
    PROJECT_SYNCHRONOUS,
    get_kube_context_and_api_client,
    make_name_dns_safe,
)
from .abstract import AbstractRun, AbstractRunner
from .kubernetes_monitor import KubernetesRunMonitor

get_module(
    "kubernetes",
    required="Kubernetes runner requires the kubernetes package. Please install it with `pip install wandb[launch]`.",
)

from kubernetes import client  # type: ignore # noqa: E402
from kubernetes.client.api.batch_v1_api import BatchV1Api  # type: ignore # noqa: E402
from kubernetes.client.api.core_v1_api import CoreV1Api  # type: ignore # noqa: E402
from kubernetes.client.api.custom_objects_api import (  # type: ignore # noqa: E402
    CustomObjectsApi,
)
from kubernetes.client.models.v1_job import V1Job  # type: ignore # noqa: E402
from kubernetes.client.models.v1_secret import V1Secret  # type: ignore # noqa: E402
from kubernetes.client.rest import ApiException  # type: ignore # noqa: E402

TIMEOUT = 5

_logger = logging.getLogger(__name__)


class KubernetesSubmittedRun(AbstractRun):
    """Wrapper for a launched run on Kubernetes."""

    def __init__(
        self,
        monitor: KubernetesRunMonitor,
        batch_api: "BatchV1Api",
        core_api: "CoreV1Api",
        name: str,
        pod_names: List[str],
        namespace: Optional[str] = "default",
        secret: Optional["V1Secret"] = None,
    ) -> None:
        """Initialize a KubernetesSubmittedRun.

        Other implementations of the AbstractRun interface poll on the run
        when `get_status` is called, but KubernetesSubmittedRun uses
        Kubernetes watch streams to update the run status. One thread handles
        events from the job object and another thread handles events from the
        rank 0 pod. These threads updated the `_status` attributed of the
        KubernetesSubmittedRun object. When `get_status` is called, the
        `_status` attribute is returned.

        Arguments:
            batch_api: Kubernetes BatchV1Api object.
            core_api: Kubernetes CoreV1Api object.
            name: Name of the job.
            pod_names: List of pod names.
            namespace: Kubernetes namespace.
            secret: Kubernetes secret.

        Returns:
            None.
        """
        self.monitor = monitor
        self.batch_api = batch_api
        self.core_api = core_api
        self.name = name
        self.namespace = namespace
        self._fail_count = 0
        self.pod_names = pod_names
        self.secret = secret

    @property
    def id(self) -> str:
        """Return the run id."""
        return self.name

    def get_logs(self) -> Optional[str]:
        try:
            logs = self.core_api.read_namespaced_pod_log(
                name=self.pod_names[0], namespace=self.namespace
            )
            if logs:
                return str(logs)
            else:
                wandb.termwarn(
                    f"Retrieved no logs for kubernetes pod(s): {self.pod_names}"
                )
            return None
        except Exception as e:
            wandb.termerror(f"{LOG_PREFIX}Failed to get pod logs: {e}")
            return None

    def get_job(self) -> "V1Job":
        """Return the job object."""
        return self.batch_api.read_namespaced_job(
            name=self.name, namespace=self.namespace
        )

    def wait(self) -> bool:
        """Wait for the run to finish.

        Returns:
            True if the run finished successfully, False otherwise.
        """
        while True:
            status = self.get_status()
            wandb.termlog(f"{LOG_PREFIX}Job {self.name} status: {status}")
            if status.state in ["finished", "failed", "preempted"]:
                break
            time.sleep(5)
        return (
            status.state == "finished"
        )  # todo: not sure if this (copied from aws runner) is the right approach? should we return false on failure

    def _delete_secret_if_completed(self, state: str) -> None:
        """If the runner has a secret and the run is completed, delete the secret."""
        if state in ["stopped", "failed", "finished"] and self.secret is not None:
            try:
                self.core_api.delete_namespaced_secret(
                    self.secret.metadata.name, self.namespace
                )
            except Exception as e:
                wandb.termerror(
                    f"Error deleting secret {self.secret.metadata.name}: {str(e)}"
                )

    def get_status(self) -> Status:
        return self.monitor.get_status()

    def cancel(self) -> None:
        """Cancel the run."""
        self.monitor.stop()
        try:
            self.batch_api.delete_namespaced_job(
                namespace=self.namespace,
                name=self.name,
            )
        except ApiException as e:
            raise LaunchError(
                f"Failed to delete Kubernetes Job {self.name} in namespace {self.namespace}: {str(e)}"
            ) from e


class CrdSubmittedRun(AbstractRun):
    """Run submitted to a CRD backend, e.g. Volcano."""

    def __init__(
        self,
        group: str,
        version: str,
        plural: str,
        name: str,
        namespace: str,
        core_api: CoreV1Api,
        custom_api: CustomObjectsApi,
        monitor: KubernetesRunMonitor,
    ) -> None:
        """Create a run object for tracking the progress of a CRD.

        Arguments:
            group: The API group of the CRD.
            version: The API version of the CRD.
            plural: The plural name of the CRD.
            name: The name of the CRD instance.
            namespace: The namespace of the CRD instance.
            core_api: The Kubernetes core API client.
            custom_api: The Kubernetes custom object API client.
            monitor: The run monitor.

        Raises:
            LaunchError: If the CRD instance does not exist.
        """
        self.group = group
        self.version = version
        self.plural = plural
        self.name = name
        self.namespace = namespace
        self.core_api = core_api
        self.custom_api = custom_api
        self._fail_count = 0
        self.monitor = monitor

    @property
    def id(self) -> str:
        """Get the name of the custom object."""
        return self.name

    def get_logs(self) -> Optional[str]:
        """Get logs for custom object."""
        # TODO: test more carefully once we release multi-node support
        logs: Dict[str, Optional[str]] = {}
        try:
            pods = self.core_api.list_namespaced_pod(
                label_selector=f"wandb/run-id={self.name}", namespace=self.namespace
            )
            pod_names = [pi.metadata.name for pi in pods.items]
            for pod_name in pod_names:
                logs[pod_name] = self.core_api.read_namespaced_pod_log(
                    name=pod_name, namespace=self.namespace
                )
        except ApiException as e:
            wandb.termwarn(f"Failed to get logs for {self.name}: {str(e)}")
            return None
        if not logs:
            return None
        logs_as_array = [f"Pod {pod_name}:\n{log}" for pod_name, log in logs.items()]
        return "\n".join(logs_as_array)

    def get_status(self) -> Status:
        """Get status of custom object."""
        return self.monitor.get_status()

    def cancel(self) -> None:
        """Cancel the custom object."""
        try:
            self.custom_api.delete_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.namespace,
                plural=self.plural,
                name=self.name,
            )
        except ApiException as e:
            raise LaunchError(
                f"Failed to delete CRD {self.name} in namespace {self.namespace}: {str(e)}"
            ) from e

    def wait(self) -> bool:
        """Wait for this custom object to finish running."""
        while True:
            status = self.get_status()
            wandb.termlog(f"{LOG_PREFIX}Job {self.name} status: {status}")
            time.sleep(5)
            if status.state in ["finished", "failed", "preempted"]:
                return status.state == "finished"


class KubernetesRunner(AbstractRunner):
    """Launches runs onto kubernetes."""

    def __init__(
        self,
        api: Api,
        backend_config: Dict[str, Any],
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
    ) -> None:
        """Create a Kubernetes runner.

        Arguments:
            api: The API client object.
            backend_config: The backend configuration.
            environment: The environment to launch runs into.

        Raises:
            LaunchError: If the Kubernetes configuration is invalid.
        """
        super().__init__(api, backend_config)
        self.environment = environment
        self.registry = registry

    def get_namespace(
        self, resource_args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """Get the namespace to launch into.

        Arguments:
            resource_args: The resource args to launch.
            context: The k8s config context.

        Returns:
            The namespace to launch into.
        """
        default_namespace = (
            context["context"].get("namespace", "default") if context else "default"
        )
        return (  # type: ignore[no-any-return]
            resource_args.get("metadata", {}).get("namespace")
            or resource_args.get(
                "namespace"
            )  # continue support for malformed namespace
            or self.backend_config.get("runner", {}).get("namespace")
            or default_namespace
        )

    def _inject_defaults(
        self,
        resource_args: Dict[str, Any],
        launch_project: LaunchProject,
        image_uri: str,
        namespace: str,
        core_api: "CoreV1Api",
    ) -> Tuple[Dict[str, Any], Optional["V1Secret"]]:
        """Apply our default values, return job dict and secret.

        Arguments:
            resource_args (Dict[str, Any]): The resource args to launch.
            launch_project (LaunchProject): The launch project.
            builder (Optional[AbstractBuilder]): The builder.
            namespace (str): The namespace.
            core_api (CoreV1Api): The core api.

        Returns:
            Tuple[Dict[str, Any], Optional["V1Secret"]]: The resource args and secret.
        """
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
        entry_point = (
            launch_project.override_entrypoint
            or launch_project.get_single_entry_point()
        )
        if launch_project.docker_image:
            # dont specify run id if user provided image, could have multiple runs
            containers[0]["image"] = image_uri
            # TODO: handle secret pulling image from registry
        elif not any(["image" in cont for cont in containers]):
            assert entry_point is not None
            # in the non instance case we need to make an imagePullSecret
            # so the new job can pull the image
            containers[0]["image"] = image_uri
        secret = maybe_create_imagepull_secret(
            core_api, self.registry, launch_project.run_id, namespace
        )
        if secret is not None:
            pod_spec["imagePullSecrets"] = [
                {"name": f"regcred-{launch_project.run_id}"}
            ]

        inject_entrypoint_and_args(
            containers,
            entry_point,
            launch_project.override_args,
            launch_project.override_entrypoint is not None,
        )

        env_vars = get_env_vars_dict(
            launch_project, self._api, MAX_ENV_LENGTHS[self.__class__.__name__]
        )
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
        self, launch_project: LaunchProject, image_uri: str
    ) -> Optional[AbstractRun]:  # noqa: C901
        """Execute a launch project on Kubernetes.

        Arguments:
            launch_project: The launch project to execute.
            builder: The builder to use to build the image.

        Returns:
            The run object if the run was successful, otherwise None.
        """
        kubernetes = get_module(  # noqa: F811
            "kubernetes",
            required="Kubernetes runner requires the kubernetes package. Please"
            " install it with `pip install wandb[launch]`.",
        )
        resource_args = launch_project.fill_macros(image_uri).get("kubernetes", {})
        if not resource_args:
            wandb.termlog(
                f"{LOG_PREFIX}Note: no resource args specified. Add a "
                "Kubernetes yaml spec or other options in a json file "
                "with --resource-args <json>."
            )
        _logger.info(f"Running Kubernetes job with resource args: {resource_args}")

        context, api_client = get_kube_context_and_api_client(kubernetes, resource_args)

        # If the user specified an alternate api, we need will execute this
        # run by creating a custom object.
        api_version = resource_args.get("apiVersion", "batch/v1")
        if api_version not in ["batch/v1", "batch/v1beta1"]:
            env_vars = get_env_vars_dict(
                launch_project, self._api, MAX_ENV_LENGTHS[self.__class__.__name__]
            )
            # Crawl the resource args and add our env vars to the containers.
            add_wandb_env(resource_args, env_vars)
            # Crawl the resource arsg and add our labels to the pods. This is
            # necessary for the agent to find the pods later on.
            add_label_to_pods(resource_args, "wandb/run-id", launch_project.run_id)
            overrides = {}
            if launch_project.override_args:
                overrides["args"] = launch_project.override_args
            if launch_project.override_entrypoint:
                overrides["command"] = launch_project.override_entrypoint.command
            add_entrypoint_args_overrides(
                resource_args,
                overrides,
            )
            api = client.CustomObjectsApi(api_client)
            # Infer the attributes of a custom object from the apiVersion and/or
            # a kind: attribute in the resource args.
            namespace = self.get_namespace(resource_args, context)
            group = resource_args.get("group", api_version.split("/")[0])
            version = api_version.split("/")[1]
            kind = resource_args.get("kind", version)
            plural = f"{kind.lower()}s"
            try:
                response = api.create_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=namespace,
                    plural=plural,
                    body=resource_args,
                )
            except ApiException as e:
                body = json.loads(e.body)
                body_yaml = yaml.dump(body)
                raise LaunchError(
                    f"Error creating CRD of kind {kind}: {e.status} {e.reason}\n{body_yaml}"
                ) from e
            name = response.get("metadata", {}).get("name")
            _logger.info(f"Created {kind} {response['metadata']['name']}")
            core = client.CoreV1Api(api_client)
            run_monitor = KubernetesRunMonitor(
                job_field_selector=f"metadata.name={name}",
                pod_label_selector=f"wandb/run-id={launch_project.run_id}",
                namespace=namespace,
                batch_api=None,
                core_api=core,
                custom_api=api,
                group=group,
                version=version,
                plural=plural,
            )
            run_monitor.start()
            submitted_run = CrdSubmittedRun(
                name=name,
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                core_api=client.CoreV1Api(api_client),
                custom_api=api,
                monitor=run_monitor,
            )
            if self.backend_config[PROJECT_SYNCHRONOUS]:
                submitted_run.wait()
            return submitted_run

        batch_api = kubernetes.client.BatchV1Api(api_client)
        core_api = kubernetes.client.CoreV1Api(api_client)
        namespace = self.get_namespace(resource_args, context)
        job, secret = self._inject_defaults(
            resource_args, launch_project, image_uri, namespace, core_api
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

        # Event stream monitor to ensure pod creation and job completion.
        monitor = KubernetesRunMonitor(
            job_field_selector=f"metadata.name={job_name}",
            pod_label_selector=f"job-name={job_name}",
            namespace=namespace,
            batch_api=batch_api,
            core_api=core_api,
        )
        monitor.start()
        submitted_job = KubernetesSubmittedRun(
            monitor, batch_api, core_api, job_name, [], namespace, secret
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
    """Inject the entrypoint and args into the containers.

    Arguments:
        containers: The containers to inject the entrypoint and args into.
        entry_point: The entrypoint to inject.
        override_args: The args to inject.
        should_override_entrypoint: Whether to override the entrypoint.

    Returns:
        None
    """
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
    """Create a secret for pulling images from a private registry.

    Arguments:
        core_api: The Kubernetes CoreV1Api object.
        registry: The registry to pull from.
        run_id: The run id.
        namespace: The namespace to create the secret in.

    Returns:
        A secret if one was created, otherwise None.
    """
    secret = None
    if isinstance(registry, LocalRegistry) or isinstance(
        registry, AzureContainerRegistry
    ):
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
        try:
            return core_api.create_namespaced_secret(namespace, secret)
        except ApiException as e:
            # 409 = conflict = secret already exists
            if e.status == 409:
                return core_api.read_namespaced_secret(
                    name=f"regcred-{run_id}", namespace=namespace
                )
            raise
    except Exception as e:
        raise LaunchError(f"Exception when creating Kubernetes secret: {str(e)}\n")


def add_wandb_env(root: Union[dict, list], env_vars: Dict[str, str]) -> None:
    """Injects wandb environment variables into specs.

    Recursively walks the spec and injects the environment variables into
    every container spec. Containers are identified by the "containers" key.

    This function treats the WANDB_RUN_ID and WANDB_GROUP_ID environment variables
    specially. If they are present in the spec, they will be overwritten. If a setting
    for WANDB_RUN_ID is provided in env_vars, then that environment variable will only be
    set in the first container modified by this function.

    Arguments:
        root: The spec to modify.
        env_vars: The environment variables to inject.

    Returns: None.
    """

    def yield_containers(root: Any) -> Iterator[dict]:
        if isinstance(root, dict):
            for k, v in root.items():
                if k == "containers":
                    if isinstance(v, list):
                        yield from v
                elif isinstance(v, (dict, list)):
                    yield from yield_containers(v)
        elif isinstance(root, list):
            for item in root:
                yield from yield_containers(item)

    for cont in yield_containers(root):
        env = cont.setdefault("env", [])
        env.extend([{"name": key, "value": value} for key, value in env_vars.items()])
        cont["env"] = env
        # After we have set WANDB_RUN_ID once, we don't want to set it again
        if "WANDB_RUN_ID" in env_vars:
            env_vars.pop("WANDB_RUN_ID")


def add_label_to_pods(
    manifest: Union[dict, list], label_key: str, label_value: str
) -> None:
    """Add a label to all pod specs in a manifest.

    Recursively traverses the manifest and adds the label to all pod specs.
    Pod specs are identified by the presence of a "spec" key with a "containers"
    key in the value.

    Arguments:
        manifest: The manifest to modify.
        label_key: The label key to add.
        label_value: The label value to add.

    Returns: None.
    """

    def yield_pods(manifest: Any) -> Iterator[dict]:
        if isinstance(manifest, list):
            for item in manifest:
                yield from yield_pods(item)
        elif isinstance(manifest, dict):
            if "spec" in manifest and "containers" in manifest["spec"]:
                yield manifest
            for value in manifest.values():
                if isinstance(value, (dict, list)):
                    yield from yield_pods(value)

    for pod in yield_pods(manifest):
        metadata = pod.setdefault("metadata", {})
        labels = metadata.setdefault("labels", {})
        labels[label_key] = label_value


def add_entrypoint_args_overrides(manifest: Union[dict, list], overrides: dict) -> None:
    """Add entrypoint and args overrides to all containers in a manifest.

    Recursively traverses the manifest and adds the entrypoint and args overrides
    to all containers. Containers are identified by the presence of a "spec" key
    with a "containers" key in the value.

    Arguments:
        manifest: The manifest to modify.
        overrides: Dictionary with args and entrypoint keys.

    Returns: None.
    """
    if isinstance(manifest, list):
        for item in manifest:
            add_entrypoint_args_overrides(item, overrides)
    elif isinstance(manifest, dict):
        if "spec" in manifest and "containers" in manifest["spec"]:
            containers = manifest["spec"]["containers"]
            for container in containers:
                if "command" in overrides:
                    container["command"] = overrides["command"]
                if "args" in overrides:
                    container["args"] = overrides["args"]
        for value in manifest.values():
            add_entrypoint_args_overrides(value, overrides)
