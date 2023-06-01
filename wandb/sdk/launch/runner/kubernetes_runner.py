"""Implementation of KubernetesRunner class for wandb launch."""

import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.registry.local_registry import LocalRegistry
from wandb.sdk.launch.runner.abstract import State, Status
from wandb.util import get_module

from .._project_spec import EntryPoint, LaunchProject
from ..builder.build import get_env_vars_dict
from ..errors import LaunchError
from ..utils import (
    LOG_PREFIX,
    PROJECT_SYNCHRONOUS,
    get_kube_context_and_api_client,
    make_name_dns_safe,
)
from .abstract import AbstractRun, AbstractRunner

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
MAX_KUBERNETES_RETRIES = (
    60  # default 10 second loop time on the agent, this is 10 minutes
)
FAIL_MESSAGE_INTERVAL = 60

_logger = logging.getLogger(__name__)


# Dict for mapping possible states of custom objects to the states we want to report
# to the agent.
CRD_STATE_DICT: Dict[str, State] = {
    "pending": "starting",
    "running": "running",
    "completed": "finished",
    "failed": "failed",
    "aborted": "failed",
    "terminating": "stopping",
    "terminated": "stopped",
}


class KubernetesSubmittedRun(AbstractRun):
    """Wrapper for a launched run on Kubernetes."""

    def __init__(
        self,
        batch_api: "BatchV1Api",
        core_api: "CoreV1Api",
        name: str,
        pod_names: List[str],
        namespace: Optional[str] = "default",
        secret: Optional["V1Secret"] = None,
    ) -> None:
        """Initialize a KubernetesSubmittedRun.

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
        """Return the run id."""
        return self.name

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
            if status.state != "running":
                break
            time.sleep(5)
        return (
            status.state == "finished"
        )  # todo: not sure if this (copied from aws runner) is the right approach? should we return false on failure

    def get_status(self) -> Status:
        """Return the run status."""
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
        """Suspend the run."""
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
        """Cancel the run."""
        self.suspend()
        self.batch_api.delete_namespaced_job(name=self.name, namespace=self.namespace)


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
        pod_names: List[str],
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
            pod_names: The names of the pods associated with the CRD instance.

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
        self.pod_names = pod_names
        self._fail_count = 0
        try:
            self.job = self.custom_api.get_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.namespace,
                plural=self.plural,
                name=self.name,
            )
        except ApiException as e:
            raise LaunchError(
                f"Failed to get CRD {self.name} in namespace {self.namespace}: {str(e)}"
            ) from e

    @property
    def id(self) -> str:
        """Get the name of the custom object."""
        return self.name

    def get_status(self) -> Status:
        """Get status of custom object."""
        try:
            job_response = self.custom_api.get_namespaced_custom_object_status(
                group=self.group,
                version=self.version,
                namespace=self.namespace,
                plural=self.plural,
                name=self.name,
            )
        except ApiException as e:
            raise LaunchError(
                f"Failed to get CRD {self.name} in namespace {self.namespace}: {str(e)}"
            ) from e
        # Custom objects can technically define whater states and format the
        # response to the status request however they want. This checks for
        # the most common cases.
        status = job_response["status"]
        state = status.get("state")
        if isinstance(state, dict):
            state = state.get("phase")
        if state is None:
            raise LaunchError(
                f"Failed to get CRD {self.name} in namespace {self.namespace}: no state found"
            )
        return Status(CRD_STATE_DICT.get(state.lower(), "unknown"))

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
            if status.state != "running":
                break
            time.sleep(5)
        return status.state == "finished"


class KubernetesRunner(AbstractRunner):
    """Launches runs onto kubernetes."""

    def __init__(
        self, api: Api, backend_config: Dict[str, Any], environment: AbstractEnvironment
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

    def wait_job_launch(
        self,
        job_name: str,
        namespace: str,
        core_api: "CoreV1Api",
        label: str = "job-name",
    ) -> List[str]:
        """Wait for a job to be launched and return the pod names.

        Arguments:
            job_name: The name of the job.
            namespace: The namespace of the job.
            core_api: The Kubernetes core API client.
            label: The label key to match against job_name.

        Returns:
            The names of the pods associated with the job.
        """
        pods = core_api.list_namespaced_pod(
            label_selector=f"{label}={job_name}", namespace=namespace
        )
        timeout = TIMEOUT
        while len(pods.items) == 0 and timeout > 0:
            time.sleep(1)
            timeout -= 1
            pods = core_api.list_namespaced_pod(
                label_selector=f"{label}={job_name}", namespace=namespace
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
        entry_point = launch_project.get_single_entry_point()
        if launch_project.docker_image:
            if len(containers) > 1:
                raise LaunchError(
                    "Invalid specification of multiple containers. See https://docs.wandb.ai/guides/launch for guidance on submitting jobs."
                )
            # dont specify run id if user provided image, could have multiple runs
            containers[0]["image"] = launch_project.docker_image
            # TODO: handle secret pulling image from registry
            launch_project.fill_macros(launch_project.docker_image)
        elif not any(["image" in cont for cont in containers]):
            if len(containers) > 1:
                raise LaunchError(
                    "Launch only builds one container at a time. See https://docs.wandb.ai/guides/launch for guidance on submitting jobs."
                )
            assert entry_point is not None
            assert builder is not None
            image_uri = builder.build_image(launch_project, entry_point)
            launch_project.fill_macros(image_uri)
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
            launch_project.fill_macros(image_uri)

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
        builder: AbstractBuilder,
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
        resource_args = launch_project.resource_args.get("kubernetes", {})
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
            entrypoint = launch_project.get_single_entry_point()
            if launch_project.docker_image:
                image_uri = launch_project.docker_image
            else:
                assert entrypoint is not None
                image_uri = builder.build_image(launch_project, entrypoint)
            launch_project.fill_macros(image_uri)
            env_vars = get_env_vars_dict(launch_project, self._api)
            # Crawl the resource args and add our env vars to the containers.
            add_wandb_env(launch_project.resource_args, env_vars)
            # Crawl the resource arsg and add our labels to the pods. This is
            # necessary for the agent to find the pods later on.
            add_label_to_pods(
                launch_project.resource_args, "wandb/run-id", launch_project.run_id
            )
            overrides = {}
            if launch_project.override_args:
                overrides["args"] = launch_project.override_args
            if launch_project.override_entrypoint:
                overrides["command"] = launch_project.override_entrypoint.command
            add_entrypoint_args_overrides(
                launch_project.resource_args,
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
                    body=launch_project.resource_args.get("kubernetes"),
                )
            except ApiException as e:
                raise LaunchError(
                    f"Error creating CRD of kind {kind}: {e.status} {e.reason}"
                ) from e
            name = response.get("metadata", {}).get("name")
            _logger.info(f"Created {kind} {response['metadata']['name']}")
            core = client.CoreV1Api(api_client)
            pod_names = self.wait_job_launch(
                launch_project.run_id, namespace, core, label="wandb/run-id"
            )
            return CrdSubmittedRun(
                name=name,
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                core_api=client.CoreV1Api(api_client),
                custom_api=api,
                pod_names=pod_names,
            )

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


def add_wandb_env(root: Union[dict, list], env_vars: Dict[str, str]) -> None:
    """Injects wandb environment variables into specs.

    Recursively walks the spec and injects the environment variables into
    every container spec. Containers are identified by the "containers" key.

    Arguments:
        root: The spec to modify.
        env_vars: The environment variables to inject.

    Returns: None.
    """
    if isinstance(root, dict):
        for k, v in root.items():
            if k == "containers":
                if isinstance(v, list):
                    for cont in v:
                        env = cont.get("env", [])
                        env.extend(
                            [
                                {"name": key, "value": value}
                                for key, value in env_vars.items()
                            ]
                        )
                        cont["env"] = env
            elif isinstance(v, (dict, list)):
                add_wandb_env(v, env_vars)
    elif isinstance(root, list):
        for item in root:
            add_wandb_env(item, env_vars)


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
    if isinstance(manifest, list):
        for item in manifest:
            add_label_to_pods(item, label_key, label_value)
    elif isinstance(manifest, dict):
        if "spec" in manifest and "containers" in manifest["spec"]:
            metadata = manifest.setdefault("metadata", {})
            labels = metadata.setdefault("labels", {})
            labels[label_key] = label_value
        for value in manifest.values():
            add_label_to_pods(value, label_key, label_value)


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
