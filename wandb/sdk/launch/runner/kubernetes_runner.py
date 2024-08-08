"""Implementation of KubernetesRunner class for wandb launch."""

import asyncio
import base64
import datetime
import json
import logging
import os
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import yaml

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.registry.azure_container_registry import AzureContainerRegistry
from wandb.sdk.launch.registry.local_registry import LocalRegistry
from wandb.sdk.launch.runner.abstract import Status
from wandb.sdk.launch.runner.kubernetes_monitor import (
    WANDB_K8S_LABEL_AGENT,
    WANDB_K8S_LABEL_MONITOR,
    WANDB_K8S_RUN_ID,
    CustomResource,
    LaunchKubernetesMonitor,
)
from wandb.sdk.lib.retry import ExponentialBackoff, retry_async
from wandb.util import get_module

from .._project_spec import EntryPoint, LaunchProject
from ..errors import LaunchError
from ..utils import (
    CODE_MOUNT_DIR,
    LOG_PREFIX,
    MAX_ENV_LENGTHS,
    PROJECT_SYNCHRONOUS,
    get_kube_context_and_api_client,
    make_name_dns_safe,
)
from .abstract import AbstractRun, AbstractRunner

get_module(
    "kubernetes_asyncio",
    required="Kubernetes runner requires the kubernetes package. Please install it with `pip install wandb[launch]`.",
)

import kubernetes_asyncio  # type: ignore # noqa: E402
from kubernetes_asyncio import client  # noqa: E402
from kubernetes_asyncio.client.api.batch_v1_api import (  # type: ignore # noqa: E402
    BatchV1Api,
)
from kubernetes_asyncio.client.api.core_v1_api import (  # type: ignore # noqa: E402
    CoreV1Api,
)
from kubernetes_asyncio.client.api.custom_objects_api import (  # type: ignore # noqa: E402
    CustomObjectsApi,
)
from kubernetes_asyncio.client.models.v1_secret import (  # type: ignore # noqa: E402
    V1Secret,
)
from kubernetes_asyncio.client.rest import ApiException  # type: ignore # noqa: E402

TIMEOUT = 5
API_KEY_SECRET_MAX_RETRIES = 5

_logger = logging.getLogger(__name__)


SOURCE_CODE_PVC_MOUNT_PATH = os.environ.get("WANDB_LAUNCH_CODE_PVC_MOUNT_PATH")
SOURCE_CODE_PVC_NAME = os.environ.get("WANDB_LAUNCH_CODE_PVC_NAME")


class KubernetesSubmittedRun(AbstractRun):
    """Wrapper for a launched run on Kubernetes."""

    def __init__(
        self,
        batch_api: "BatchV1Api",
        core_api: "CoreV1Api",
        name: str,
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
            namespace: Kubernetes namespace.
            secret: Kubernetes secret.

        Returns:
            None.
        """
        self.batch_api = batch_api
        self.core_api = core_api
        self.name = name
        self.namespace = namespace
        self._fail_count = 0
        self.secret = secret

    @property
    def id(self) -> str:
        """Return the run id."""
        return self.name

    async def get_logs(self) -> Optional[str]:
        try:
            pods = await self.core_api.list_namespaced_pod(
                label_selector=f"job-name={self.name}", namespace=self.namespace
            )
            pod_names = [pi.metadata.name for pi in pods.items]
            if not pod_names:
                wandb.termwarn(f"Found no pods for kubernetes job: {self.name}")
                return None
            logs = await self.core_api.read_namespaced_pod_log(
                name=pod_names[0], namespace=self.namespace
            )
            if logs:
                return str(logs)
            else:
                wandb.termwarn(f"No logs for kubernetes pod(s): {pod_names}")
            return None
        except Exception as e:
            wandb.termerror(f"{LOG_PREFIX}Failed to get pod logs: {e}")
            return None

    async def wait(self) -> bool:
        """Wait for the run to finish.

        Returns:
            True if the run finished successfully, False otherwise.
        """
        while True:
            status = await self.get_status()
            wandb.termlog(f"{LOG_PREFIX}Job {self.name} status: {status.state}")
            if status.state in ["finished", "failed", "preempted"]:
                break
            await asyncio.sleep(5)

        await self._delete_secret()
        return (
            status.state == "finished"
        )  # todo: not sure if this (copied from aws runner) is the right approach? should we return false on failure

    async def get_status(self) -> Status:
        status = LaunchKubernetesMonitor.get_status(self.name)
        if status in ["stopped", "failed", "finished", "preempted"]:
            await self._delete_secret()
        return status

    async def cancel(self) -> None:
        """Cancel the run."""
        try:
            await self.batch_api.delete_namespaced_job(
                namespace=self.namespace,
                name=self.name,
            )
            await self._delete_secret()
        except ApiException as e:
            raise LaunchError(
                f"Failed to delete Kubernetes Job {self.name} in namespace {self.namespace}: {str(e)}"
            ) from e

    async def _delete_secret(self) -> None:
        # Cleanup secret if not running in a helm-managed context
        if not os.environ.get("WANDB_RELEASE_NAME") and self.secret:
            await self.core_api.delete_namespaced_secret(
                name=self.secret.metadata.name,
                namespace=self.secret.metadata.namespace,
            )
            self.secret = None


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

    @property
    def id(self) -> str:
        """Get the name of the custom object."""
        return self.name

    async def get_logs(self) -> Optional[str]:
        """Get logs for custom object."""
        # TODO: test more carefully once we release multi-node support
        logs: Dict[str, Optional[str]] = {}
        try:
            pods = await self.core_api.list_namespaced_pod(
                label_selector=f"wandb/run-id={self.name}", namespace=self.namespace
            )
            pod_names = [pi.metadata.name for pi in pods.items]
            for pod_name in pod_names:
                logs[pod_name] = await self.core_api.read_namespaced_pod_log(
                    name=pod_name, namespace=self.namespace
                )
        except ApiException as e:
            wandb.termwarn(f"Failed to get logs for {self.name}: {str(e)}")
            return None
        if not logs:
            return None
        logs_as_array = [f"Pod {pod_name}:\n{log}" for pod_name, log in logs.items()]
        return "\n".join(logs_as_array)

    async def get_status(self) -> Status:
        """Get status of custom object."""
        return LaunchKubernetesMonitor.get_status(self.name)

    async def cancel(self) -> None:
        """Cancel the custom object."""
        try:
            await self.custom_api.delete_namespaced_custom_object(
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

    async def wait(self) -> bool:
        """Wait for this custom object to finish running."""
        while True:
            status = await self.get_status()
            wandb.termlog(f"{LOG_PREFIX}Job {self.name} status: {status}")
            if status.state in ["finished", "failed", "preempted"]:
                return status.state == "finished"
            await asyncio.sleep(5)


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

    async def _inject_defaults(
        self,
        resource_args: Dict[str, Any],
        launch_project: LaunchProject,
        image_uri: str,
        namespace: str,
        core_api: "CoreV1Api",
    ) -> Tuple[Dict[str, Any], Optional["V1Secret"]]:
        """Apply our default values, return job dict and api key secret.

        Arguments:
            resource_args (Dict[str, Any]): The resource args to launch.
            launch_project (LaunchProject): The launch project.
            builder (Optional[AbstractBuilder]): The builder.
            namespace (str): The namespace.
            core_api (CoreV1Api): The core api.

        Returns:
            Tuple[Dict[str, Any], Optional["V1Secret"]]: The resource args and api key secret.
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

        # Add labels to job metadata
        job_metadata.setdefault("labels", {})
        job_metadata["labels"][WANDB_K8S_RUN_ID] = launch_project.run_id
        job_metadata["labels"][WANDB_K8S_LABEL_MONITOR] = "true"
        if LaunchAgent.initialized():
            job_metadata["labels"][WANDB_K8S_LABEL_AGENT] = LaunchAgent.name()
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

        entry_point = (
            launch_project.override_entrypoint or launch_project.get_job_entry_point()
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
        secret = await maybe_create_imagepull_secret(
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

        env_vars = launch_project.get_env_vars_dict(
            self._api, MAX_ENV_LENGTHS[self.__class__.__name__]
        )
        api_key_secret = None
        for cont in containers:
            # Add our env vars to user supplied env vars
            env = cont.get("env") or []
            for key, value in env_vars.items():
                if (
                    key == "WANDB_API_KEY"
                    and value
                    and (
                        LaunchAgent.initialized()
                        or self.backend_config[PROJECT_SYNCHRONOUS]
                    )
                ):
                    # Override API key with secret. TODO: Do the same for other runners
                    release_name = os.environ.get("WANDB_RELEASE_NAME")
                    secret_name = "wandb-api-key"
                    if release_name:
                        secret_name += f"-{release_name}"
                    else:
                        secret_name += f"-{launch_project.run_id}"

                    def handle_exception(e):
                        wandb.termwarn(
                            f"Exception when ensuring Kubernetes API key secret: {e}. Retrying..."
                        )

                    api_key_secret = await retry_async(
                        backoff=ExponentialBackoff(
                            initial_sleep=datetime.timedelta(seconds=1),
                            max_sleep=datetime.timedelta(minutes=1),
                            max_retries=API_KEY_SECRET_MAX_RETRIES,
                        ),
                        fn=ensure_api_key_secret,
                        on_exc=handle_exception,
                        core_api=core_api,
                        secret_name=secret_name,
                        namespace=namespace,
                        api_key=value,
                    )
                    env.append(
                        {
                            "name": key,
                            "valueFrom": {
                                "secretKeyRef": {
                                    "name": secret_name,
                                    "key": "password",
                                }
                            },
                        }
                    )
                else:
                    env.append({"name": key, "value": value})
            cont["env"] = env

        pod_spec["containers"] = containers
        pod_template["spec"] = pod_spec
        job_spec["template"] = pod_template
        job["spec"] = job_spec
        job["metadata"] = job_metadata

        add_label_to_pods(
            job,
            WANDB_K8S_LABEL_MONITOR,
            "true",
        )

        if launch_project.job_base_image:
            apply_code_mount_configuration(
                job,
                launch_project,
            )

        # Add wandb.ai/agent: current agent label on all pods
        if LaunchAgent.initialized():
            add_label_to_pods(
                job,
                WANDB_K8S_LABEL_AGENT,
                LaunchAgent.name(),
            )

        return job, api_key_secret

    async def run(
        self, launch_project: LaunchProject, image_uri: str
    ) -> Optional[AbstractRun]:  # noqa: C901
        """Execute a launch project on Kubernetes.

        Arguments:
            launch_project: The launch project to execute.
            builder: The builder to use to build the image.

        Returns:
            The run object if the run was successful, otherwise None.
        """
        await LaunchKubernetesMonitor.ensure_initialized()
        resource_args = launch_project.fill_macros(image_uri).get("kubernetes", {})
        if not resource_args:
            wandb.termlog(
                f"{LOG_PREFIX}Note: no resource args specified. Add a "
                "Kubernetes yaml spec or other options in a json file "
                "with --resource-args <json>."
            )
        _logger.info(f"Running Kubernetes job with resource args: {resource_args}")

        context, api_client = await get_kube_context_and_api_client(
            kubernetes_asyncio, resource_args
        )

        # If using pvc for code mount, move code there.
        if launch_project.job_base_image is not None:
            if SOURCE_CODE_PVC_NAME is None or SOURCE_CODE_PVC_MOUNT_PATH is None:
                raise LaunchError(
                    "WANDB_LAUNCH_SOURCE_CODE_PVC_ environment variables not set. "
                    "Unable to mount source code PVC into base image. "
                    "Use the `codeMountPvcName` variable in the agent helm chart "
                    "to enable base image jobs for this agent. See "
                    "https://github.com/wandb/helm-charts/tree/main/charts/launch-agent "
                    "for more information."
                )
            code_subdir = launch_project.get_image_source_string()
            launch_project.change_project_dir(
                os.path.join(SOURCE_CODE_PVC_MOUNT_PATH, code_subdir)
            )

        # If the user specified an alternate api, we need will execute this
        # run by creating a custom object.
        api_version = resource_args.get("apiVersion", "batch/v1")

        if api_version not in ["batch/v1", "batch/v1beta1"]:
            env_vars = launch_project.get_env_vars_dict(
                self._api, MAX_ENV_LENGTHS[self.__class__.__name__]
            )
            # Crawl the resource args and add our env vars to the containers.
            add_wandb_env(resource_args, env_vars)

            # Add our labels to the resource args. This is necessary for the
            # agent to find the custom object later on.
            resource_args["metadata"] = resource_args.get("metadata", {})
            resource_args["metadata"]["labels"] = resource_args["metadata"].get(
                "labels", {}
            )
            resource_args["metadata"]["labels"][WANDB_K8S_LABEL_MONITOR] = "true"

            # Crawl the resource arsg and add our labels to the pods. This is
            # necessary for the agent to find the pods later on.
            add_label_to_pods(
                resource_args,
                WANDB_K8S_LABEL_MONITOR,
                "true",
            )

            # Add wandb.ai/agent: current agent label on all pods
            if LaunchAgent.initialized():
                add_label_to_pods(
                    resource_args,
                    WANDB_K8S_LABEL_AGENT,
                    LaunchAgent.name(),
                )
                resource_args["metadata"]["labels"][WANDB_K8S_LABEL_AGENT] = (
                    LaunchAgent.name()
                )

            if launch_project.job_base_image:
                apply_code_mount_configuration(resource_args, launch_project)

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
            group, version, *_ = api_version.split("/")
            group = resource_args.get("group", group)
            version = resource_args.get("version", version)
            kind = resource_args.get("kind", version)
            plural = f"{kind.lower()}s"
            custom_resource = CustomResource(
                group=group,
                version=version,
                plural=plural,
            )
            LaunchKubernetesMonitor.monitor_namespace(
                namespace, custom_resource=custom_resource
            )

            try:
                response = await api.create_namespaced_custom_object(
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
            submitted_run = CrdSubmittedRun(
                name=name,
                group=group,
                version=version,
                namespace=namespace,
                plural=plural,
                core_api=client.CoreV1Api(api_client),
                custom_api=api,
            )
            if self.backend_config[PROJECT_SYNCHRONOUS]:
                await submitted_run.wait()
            return submitted_run

        batch_api = kubernetes_asyncio.client.BatchV1Api(api_client)
        core_api = kubernetes_asyncio.client.CoreV1Api(api_client)
        namespace = self.get_namespace(resource_args, context)
        job, secret = await self._inject_defaults(
            resource_args, launch_project, image_uri, namespace, core_api
        )
        msg = "Creating Kubernetes job"
        if "name" in resource_args:
            msg += f": {resource_args['name']}"
        _logger.info(msg)
        try:
            response = await kubernetes_asyncio.utils.create_from_dict(
                api_client, job, namespace=namespace
            )
        except kubernetes_asyncio.utils.FailToCreateError as e:
            for exc in e.api_exceptions:
                resp = json.loads(exc.body)
                msg = resp.get("message")
                code = resp.get("code")
                raise LaunchError(
                    f"Failed to create Kubernetes job for run {launch_project.run_id} ({code} {exc.reason}): {msg}"
                )
        except Exception as e:
            raise LaunchError(
                f"Unexpected exception when creating Kubernetes job: {str(e)}\n"
            )
        job_response = response[0]
        job_name = job_response.metadata.name
        LaunchKubernetesMonitor.monitor_namespace(namespace)
        submitted_job = KubernetesSubmittedRun(
            batch_api, core_api, job_name, namespace, secret
        )
        if self.backend_config[PROJECT_SYNCHRONOUS]:
            await submitted_job.wait()

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


async def ensure_api_key_secret(
    core_api: "CoreV1Api",
    secret_name: str,
    namespace: str,
    api_key: str,
) -> "V1Secret":
    """Create a secret containing a user's wandb API key.

    Arguments:
        core_api: The Kubernetes CoreV1Api object.
        secret_name: The name to use for the secret.
        namespace: The namespace to create the secret in.
        api_key: The user's wandb API key

    Returns:
        The created secret
    """
    secret_data = {"password": base64.b64encode(api_key.encode()).decode()}
    labels = {"wandb.ai/created-by": "launch-agent"}
    secret = client.V1Secret(
        data=secret_data,
        metadata=client.V1ObjectMeta(
            name=secret_name, namespace=namespace, labels=labels
        ),
        kind="Secret",
        type="kubernetes.io/basic-auth",
    )

    try:
        try:
            return await core_api.create_namespaced_secret(namespace, secret)
        except ApiException as e:
            # 409 = conflict = secret already exists
            if e.status == 409:
                existing_secret = await core_api.read_namespaced_secret(
                    name=secret_name, namespace=namespace
                )
                if existing_secret.data != secret_data:
                    # If it's a previous secret made by launch agent, clean it up
                    if (
                        existing_secret.metadata.labels.get("wandb.ai/created-by")
                        == "launch-agent"
                    ):
                        await core_api.delete_namespaced_secret(
                            name=secret_name, namespace=namespace
                        )
                        return await core_api.create_namespaced_secret(
                            namespace, secret
                        )
                    else:
                        raise LaunchError(
                            f"Kubernetes secret already exists in namespace {namespace} with incorrect data: {secret_name}"
                        )
                return existing_secret
            raise
    except Exception as e:
        raise LaunchError(
            f"Exception when ensuring Kubernetes API key secret: {str(e)}\n"
        )


async def maybe_create_imagepull_secret(
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
    uname, token = await registry.get_username_password()
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
            return await core_api.create_namespaced_secret(namespace, secret)
        except ApiException as e:
            # 409 = conflict = secret already exists
            if e.status == 409:
                return await core_api.read_namespaced_secret(
                    name=f"regcred-{run_id}", namespace=namespace
                )
            raise
    except Exception as e:
        raise LaunchError(f"Exception when creating Kubernetes secret: {str(e)}\n")


def yield_containers(root: Any) -> Iterator[dict]:
    """Yield all container specs in a manifest.

    Recursively traverses the manifest and yields all container specs. Container
    specs are identified by the presence of a "containers" key in the value.
    """
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
    for cont in yield_containers(root):
        env = cont.setdefault("env", [])
        env.extend([{"name": key, "value": value} for key, value in env_vars.items()])
        cont["env"] = env
        # After we have set WANDB_RUN_ID once, we don't want to set it again
        if "WANDB_RUN_ID" in env_vars:
            env_vars.pop("WANDB_RUN_ID")


def yield_pods(manifest: Any) -> Iterator[dict]:
    """Yield all pod specs in a manifest.

    Recursively traverses the manifest and yields all pod specs. Pod specs are
    identified by the presence of a "spec" key with a "containers" key in the
    value.
    """
    if isinstance(manifest, list):
        for item in manifest:
            yield from yield_pods(item)
    elif isinstance(manifest, dict):
        if "spec" in manifest and "containers" in manifest["spec"]:
            yield manifest
        for value in manifest.values():
            if isinstance(value, (dict, list)):
                yield from yield_pods(value)


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


def apply_code_mount_configuration(
    manifest: Union[Dict, list], project: LaunchProject
) -> None:
    """Apply code mount configuration to all containers in a manifest.

    Recursively traverses the manifest and adds the code mount configuration to
    all containers. Containers are identified by the presence of a "spec" key
    with a "containers" key in the value.

    Arguments:
        manifest: The manifest to modify.
        project: The launch project.

    Returns: None.
    """
    assert SOURCE_CODE_PVC_NAME is not None
    source_dir = project.get_image_source_string()
    for pod in yield_pods(manifest):
        for container in yield_containers(pod):
            if "volumeMounts" not in container:
                container["volumeMounts"] = []
            container["volumeMounts"].append(
                {
                    "name": "wandb-source-code-volume",
                    "mountPath": CODE_MOUNT_DIR,
                    "subPath": source_dir,
                }
            )
            container["workingDir"] = CODE_MOUNT_DIR
        spec = pod["spec"]
        if "volumes" not in spec:
            spec["volumes"] = []
        spec["volumes"].append(
            {
                "name": "wandb-source-code-volume",
                "persistentVolumeClaim": {
                    "claimName": SOURCE_CODE_PVC_NAME,
                },
            }
        )
