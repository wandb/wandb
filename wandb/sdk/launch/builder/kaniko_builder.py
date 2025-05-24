import asyncio
import base64
import copy
import json
import logging
import os
import shutil
import tarfile
import tempfile
import time
import traceback
from typing import Any, Dict, Optional

import wandb
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.builder.abstract import AbstractBuilder, registry_from_uri
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.environment.azure_environment import AzureEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.registry.azure_container_registry import AzureContainerRegistry
from wandb.sdk.launch.registry.elastic_container_registry import (
    ElasticContainerRegistry,
)
from wandb.sdk.launch.registry.google_artifact_registry import GoogleArtifactRegistry
from wandb.util import get_module

from .._project_spec import EntryPoint, LaunchProject
from ..errors import LaunchError
from ..utils import (
    LOG_PREFIX,
    get_kube_context_and_api_client,
    warn_failed_packages_from_build_logs,
)
from .build import _WANDB_DOCKERFILE_NAME
from .context_manager import BuildContextManager

get_module(
    "kubernetes_asyncio",
    required="Kaniko builder requires the kubernetes_asyncio package. Please install it with `pip install wandb[launch]`.",
)

import kubernetes_asyncio as kubernetes  # type: ignore # noqa: E402
from kubernetes_asyncio import client  # noqa: E402

_logger = logging.getLogger(__name__)

_DEFAULT_BUILD_TIMEOUT_SECS = 1800  # 30 minute build timeout

SERVICE_ACCOUNT_NAME = os.environ.get("WANDB_LAUNCH_SERVICE_ACCOUNT_NAME", "default")
PVC_NAME = os.environ.get("WANDB_LAUNCH_KANIKO_PVC_NAME")
PVC_MOUNT_PATH = (
    os.environ.get("WANDB_LAUNCH_KANIKO_PVC_MOUNT_PATH", "/kaniko").rstrip("/")
    if PVC_NAME
    else None
)
DOCKER_CONFIG_SECRET = os.environ.get("WANDB_LAUNCH_KANIKO_AUTH_SECRET")


if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/namespace"):
    with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as f:
        NAMESPACE = f.read().strip()
else:
    NAMESPACE = "wandb"


def get_pod_name_safe(job: client.V1Job):
    try:
        return job.spec.template.metadata.name
    except AttributeError:
        return None


async def _wait_for_completion(
    batch_client: client.BatchV1Api, job_name: str, deadline_secs: Optional[int] = None
) -> bool:
    start_time = time.time()
    while True:
        job = await batch_client.read_namespaced_job_status(job_name, NAMESPACE)
        if job.status.succeeded is not None and job.status.succeeded >= 1:
            return True
        elif job.status.failed is not None and job.status.failed >= 1:
            wandb.termerror(f"{LOG_PREFIX}Build job {job.status.failed} failed {job}")
            return False
        wandb.termlog(f"{LOG_PREFIX}Waiting for build job to complete...")
        if deadline_secs is not None and time.time() - start_time > deadline_secs:
            return False

        await asyncio.sleep(5)


class KanikoBuilder(AbstractBuilder):
    """Builds a docker image for a project using Kaniko."""

    type = "kaniko"

    build_job_name: str
    build_context_store: str
    secret_name: Optional[str]
    secret_key: Optional[str]
    image: str

    def __init__(
        self,
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
        build_job_name: str = "wandb-launch-container-build",
        build_context_store: str = "",
        secret_name: str = "",
        secret_key: str = "",
        image: str = "gcr.io/kaniko-project/executor:v1.11.0",
        config: Optional[dict] = None,
    ):
        """Initialize a KanikoBuilder.

        Arguments:
            environment (AbstractEnvironment): The environment to use.
            registry (AbstractRegistry): The registry to use.
            build_job_name (str, optional): The name of the build job.
            build_context_store (str, optional): The name of the build context store.
            secret_name (str, optional): The name of the secret to use for the registry.
            secret_key (str, optional): The key of the secret to use for the registry.
            verify (bool, optional): Whether to verify the functionality of the builder.
                Defaults to True.
        """
        self.environment = environment
        self.registry = registry
        self.build_job_name = build_job_name
        self.build_context_store = build_context_store.rstrip("/")
        self.secret_name = secret_name
        self.secret_key = secret_key
        self.image = image
        self.kaniko_config = config or {}

    @classmethod
    def from_config(
        cls,
        config: dict,
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
        verify: bool = True,
        login: bool = True,
    ) -> "AbstractBuilder":
        """Create a KanikoBuilder from a config dict.

        Arguments:
            config: A dict containing the builder config. Must contain a "type" key
                with value "kaniko".
            environment: The environment to use for the build.
            registry: The registry to use for the build.
            verify: Whether to verify the builder config.

        Returns:
            A KanikoBuilder instance.
        """
        if config.get("type") != "kaniko":
            raise LaunchError(
                "Builder config must include 'type':'kaniko' to create a KanikoBuilder."
            )
        build_context_store = config.get("build-context-store", "")
        if build_context_store is None:
            if not PVC_MOUNT_PATH:
                raise LaunchError(
                    "You must specify a build context store for kaniko builds. "
                    "You can set builder.build-context-store in your agent config "
                    "to a valid s3, gcs, or azure blog storage URI. Or, configure "
                    "a persistent volume claim through the agent helm chart: "
                    "https://github.com/wandb/helm-charts/tree/main/charts/launch-agent"
                )
        build_job_name = config.get("build-job-name", "wandb-launch-container-build")
        secret_name = config.get("secret-name", "")
        secret_key = config.get("secret-key", "")
        kaniko_image = config.get(
            "kaniko-image", "gcr.io/kaniko-project/executor:v1.11.0"
        )
        image_uri = config.get("destination")
        if image_uri is not None:
            registry = registry_from_uri(image_uri)
        kaniko_config = config.get("kaniko-config", {})

        return cls(
            environment,
            registry,
            build_context_store=build_context_store,
            build_job_name=build_job_name,
            secret_name=secret_name,
            secret_key=secret_key,
            image=kaniko_image,
            config=kaniko_config,
        )

    async def verify(self) -> None:
        """Verify that the builder config is valid.

        Raises:
            LaunchError: If the builder config is invalid.
        """
        if self.build_context_store:
            await self.environment.verify_storage_uri(self.build_context_store)

    def login(self) -> None:
        """Login to the registry."""

    async def _create_docker_ecr_config_map(
        self, job_name: str, corev1_client: client.CoreV1Api, repository: str
    ) -> None:
        username, password = await self.registry.get_username_password()
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode("utf-8")
        ecr_config_map = client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=client.V1ObjectMeta(
                name=f"docker-config-{job_name}",
                namespace=NAMESPACE,
            ),
            data={
                "config.json": json.dumps(
                    {
                        "auths": {
                            f"{await self.registry.get_repo_uri()}": {"auth": encoded}
                        }
                    }
                )
            },
            immutable=True,
        )
        await corev1_client.create_namespaced_config_map(NAMESPACE, ecr_config_map)

    async def _delete_docker_ecr_config_map(
        self, job_name: str, client: client.CoreV1Api
    ) -> None:
        if self.secret_name:
            await client.delete_namespaced_config_map(
                f"docker-config-{job_name}", NAMESPACE
            )

    async def _upload_build_context(self, run_id: str, context_path: str) -> str:
        # creat a tar archive of the build context and upload it to s3
        context_file = tempfile.NamedTemporaryFile(delete=False)
        with tarfile.TarFile.open(fileobj=context_file, mode="w:gz") as context_tgz:
            context_tgz.add(context_path, arcname=".")
        context_file.close()
        if PVC_MOUNT_PATH is None:
            destination = f"{self.build_context_store}/{run_id}.tgz"
            if self.environment is None:
                raise LaunchError("No environment specified for Kaniko build.")
            await self.environment.upload_file(context_file.name, destination)
            return destination
        else:
            destination = f"{PVC_MOUNT_PATH}/{run_id}.tgz"
            try:
                shutil.copy(context_file.name, destination)
            except Exception as e:
                raise LaunchError(
                    f"Error copying build context to PVC mounted at {PVC_MOUNT_PATH}: {e}"
                ) from e
            return f"tar:///context/{run_id}.tgz"

    async def build_image(
        self,
        launch_project: LaunchProject,
        entrypoint: EntryPoint,
        job_tracker: Optional[JobAndRunStatusTracker] = None,
    ) -> str:
        await self.verify()

        build_contex_manager = BuildContextManager(launch_project=launch_project)
        context_path, image_tag = build_contex_manager.create_build_context("kaniko")
        run_id = launch_project.run_id
        repo_uri = await self.registry.get_repo_uri()
        image_uri = repo_uri + ":" + image_tag

        # The DOCKER_CONFIG_SECRET option is mutually exclusive with the
        # registry classes, so we must skip the check for image existence in
        # that case.
        if not launch_project.build_required():
            if DOCKER_CONFIG_SECRET:
                wandb.termlog(
                    f"Skipping check for existing image {image_uri} due to custom dockerconfig."
                )
            else:
                if await self.registry.check_image_exists(image_uri):
                    return image_uri

        _logger.info(f"Building image {image_uri}...")
        _, api_client = await get_kube_context_and_api_client(
            kubernetes, launch_project.resource_args
        )
        # TODO: use same client as kubernetes_runner.py
        batch_v1 = client.BatchV1Api(api_client)
        core_v1 = client.CoreV1Api(api_client)

        build_job_name = f"{self.build_job_name}-{run_id}"

        build_context = await self._upload_build_context(run_id, context_path)
        build_job = await self._create_kaniko_job(
            build_job_name, repo_uri, image_uri, build_context, core_v1, api_client
        )
        wandb.termlog(f"{LOG_PREFIX}Created kaniko job {build_job_name}")

        try:
            # DOCKER_CONFIG_SECRET is a user provided dockerconfigjson. Skip our
            # dockerconfig handling if it's set.
            if (
                isinstance(self.registry, AzureContainerRegistry)
                and not DOCKER_CONFIG_SECRET
            ):
                dockerfile_config_map = client.V1ConfigMap(
                    metadata=client.V1ObjectMeta(
                        name=f"docker-config-{build_job_name}"
                    ),
                    data={
                        "config.json": json.dumps(
                            {
                                "credHelpers": {
                                    f"{self.registry.registry_name}.azurecr.io": "acr-env"
                                }
                            }
                        )
                    },
                )
                await core_v1.create_namespaced_config_map(
                    "wandb", dockerfile_config_map
                )
            if self.secret_name:
                await self._create_docker_ecr_config_map(
                    build_job_name, core_v1, repo_uri
                )
            k8s_job = await batch_v1.create_namespaced_job(NAMESPACE, build_job)
            # wait for double the job deadline since it might take time to schedule
            if not await _wait_for_completion(
                batch_v1, build_job_name, 3 * _DEFAULT_BUILD_TIMEOUT_SECS
            ):
                if job_tracker:
                    job_tracker.set_err_stage("build")
                msg = f"Failed to build image in kaniko for job {run_id}."
                pod_name = get_pod_name_safe(k8s_job)
                if pod_name:
                    msg += f" View logs with `kubectl logs -n {NAMESPACE} {pod_name}`."
                raise Exception(msg)  # noqa: TRY301
            try:
                pods_from_job = await core_v1.list_namespaced_pod(
                    namespace=NAMESPACE, label_selector=f"job-name={build_job_name}"
                )
                if len(pods_from_job.items) != 1:
                    raise Exception(  # noqa: TRY301
                        f"Expected 1 pod for job {build_job_name},"
                        f" found {len(pods_from_job.items)}"
                    )
                pod_name = pods_from_job.items[0].metadata.name
                logs = await core_v1.read_namespaced_pod_log(pod_name, NAMESPACE)
                warn_failed_packages_from_build_logs(
                    logs, image_uri, launch_project.api, job_tracker
                )
            except Exception as e:
                wandb.termwarn(
                    f"{LOG_PREFIX}Failed to get logs for kaniko job {build_job_name}: {e}"
                )
        except Exception as e:
            wandb.termerror(
                f"{LOG_PREFIX}Exception when creating Kubernetes resources: {e}\n"
            )
            raise
        finally:
            wandb.termlog(f"{LOG_PREFIX}Cleaning up resources")
            try:
                if (
                    isinstance(self.registry, AzureContainerRegistry)
                    and not DOCKER_CONFIG_SECRET
                ):
                    await core_v1.delete_namespaced_config_map(
                        f"docker-config-{build_job_name}", "wandb"
                    )
                if self.secret_name:
                    await self._delete_docker_ecr_config_map(build_job_name, core_v1)
                await batch_v1.delete_namespaced_job(build_job_name, NAMESPACE)
            except Exception as e:
                traceback.print_exc()
                raise LaunchError(
                    f"Exception during Kubernetes resource clean up {e}"
                ) from e
        return image_uri

    async def _create_kaniko_job(
        self,
        job_name: str,
        repository: str,
        image_tag: str,
        build_context_path: str,
        core_client: client.CoreV1Api,
        api_client,
    ) -> Dict[str, Any]:
        job = copy.deepcopy(self.kaniko_config)
        job_metadata = job.get("metadata", {})
        job_labels = job_metadata.get("labels", {})
        job_spec = job.get("spec", {})
        pod_template = job_spec.get("template", {})
        pod_metadata = pod_template.get("metadata", {})
        pod_labels = pod_metadata.get("labels", {})
        pod_spec = pod_template.get("spec", {})
        volumes = pod_spec.get("volumes", [])
        containers = pod_spec.get("containers") or [{}]
        if len(containers) > 1:
            raise LaunchError(
                "Multiple container configs not supported for kaniko builder."
            )
        container = containers[0]
        volume_mounts = container.get("volumeMounts", [])
        env = container.get("env", [])
        custom_args = container.get("args", [])

        if PVC_MOUNT_PATH:
            volumes.append(
                {"name": "kaniko-pvc", "persistentVolumeClaim": {"claimName": PVC_NAME}}
            )
            volume_mounts.append({"name": "kaniko-pvc", "mountPath": "/context"})

        if bool(self.secret_name) != bool(self.secret_key):
            raise LaunchError(
                "Both secret_name and secret_key or neither must be specified "
                "for kaniko build. You provided only one of them."
            )
        if isinstance(self.registry, ElasticContainerRegistry):
            env.append(
                {
                    "name": "AWS_REGION",
                    "value": self.registry.region,
                }
            )
        # TODO(ben): Refactor all of this environment/registry
        # specific stuff into methods of those classes.
        if isinstance(self.environment, AzureEnvironment):
            # Use the core api to check if the secret exists
            try:
                await core_client.read_namespaced_secret(
                    "azure-storage-access-key",
                    "wandb",
                )
            except Exception as e:
                raise LaunchError(
                    "Secret azure-storage-access-key does not exist in "
                    "namespace wandb. Please create it with the key password "
                    "set to your azure storage access key."
                ) from e
            env.append(
                {
                    "name": "AZURE_STORAGE_ACCESS_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": "azure-storage-access-key",
                            "key": "password",
                        }
                    },
                }
            )
        if DOCKER_CONFIG_SECRET:
            volumes.append(
                {
                    "name": "kaniko-docker-config",
                    "secret": {
                        "secretName": DOCKER_CONFIG_SECRET,
                        "items": [
                            {
                                "key": ".dockerconfigjson",
                                "path": "config.json",
                            }
                        ],
                    },
                }
            )
            volume_mounts.append(
                {"name": "kaniko-docker-config", "mountPath": "/kaniko/.docker"}
            )
        elif self.secret_name and self.secret_key:
            volumes.append(
                {
                    "name": "docker-config",
                    "configMap": {"name": f"docker-config-{job_name}"},
                }
            )
            volume_mounts.append(
                {"name": "docker-config", "mountPath": "/kaniko/.docker"}
            )
            # TODO(ben): I don't like conditioning on the registry type here. As a
            # future change I want the registry and environment classes to provide
            # a list of environment variables and volume mounts that need to be
            # added to the job. The environment class provides credentials for
            # build context access, and the registry class provides credentials
            # for pushing the image. This way we can have separate secrets for
            # each and support build contexts and registries that require
            # different credentials.
            if isinstance(self.registry, ElasticContainerRegistry):
                mount_path = "/root/.aws"
                key = "credentials"
            elif isinstance(self.registry, GoogleArtifactRegistry):
                mount_path = "/kaniko/.config/gcloud"
                key = "config.json"
                env.append(
                    {
                        "name": "GOOGLE_APPLICATION_CREDENTIALS",
                        "value": "/kaniko/.config/gcloud/config.json",
                    }
                )
            else:
                wandb.termwarn(
                    f"{LOG_PREFIX}Automatic credential handling is not supported for registry type {type(self.registry)}. Build job: {self.build_job_name}"
                )
            volumes.append(
                {
                    "name": self.secret_name,
                    "secret": {
                        "secretName": self.secret_name,
                        "items": [{"key": self.secret_key, "path": key}],
                    },
                }
            )
            volume_mounts.append(
                {
                    "name": self.secret_name,
                    "mountPath": mount_path,
                    "readOnly": True,
                }
            )
        if (
            isinstance(self.registry, AzureContainerRegistry)
            and not DOCKER_CONFIG_SECRET
        ):
            # Add the docker config map
            volumes.append(
                {
                    "name": "docker-config",
                    "configMap": {"name": f"docker-config-{job_name}"},
                }
            )
            volume_mounts.append(
                {"name": "docker-config", "mountPath": "/kaniko/.docker/"}
            )
        # Kaniko doesn't want https:// at the beginning of the image tag.
        destination = image_tag
        if destination.startswith("https://"):
            destination = destination.replace("https://", "")
        args = {
            "--context": build_context_path,
            "--dockerfile": _WANDB_DOCKERFILE_NAME,
            "--destination": destination,
            "--cache": "true",
            "--cache-repo": repository.replace("https://", ""),
            "--snapshot-mode": "redo",
            "--compressed-caching": "false",
        }
        for custom_arg in custom_args:
            arg_name, arg_value = custom_arg.split("=", 1)
            args[arg_name] = arg_value
        parsed_args = [
            f"{arg_name}={arg_value}" for arg_name, arg_value in args.items()
        ]
        container["args"] = parsed_args

        # Apply the rest of our defaults
        pod_labels["wandb"] = "launch"
        # This annotation is required to enable azure workload identity.
        # Don't add this label if using a docker config secret for auth.
        if (
            isinstance(self.registry, AzureContainerRegistry)
            and not DOCKER_CONFIG_SECRET
        ):
            pod_labels["azure.workload.identity/use"] = "true"
        pod_spec["restartPolicy"] = pod_spec.get("restartPolicy", "Never")
        pod_spec["activeDeadlineSeconds"] = pod_spec.get(
            "activeDeadlineSeconds", _DEFAULT_BUILD_TIMEOUT_SECS
        )
        pod_spec["serviceAccountName"] = pod_spec.get(
            "serviceAccountName", SERVICE_ACCOUNT_NAME
        )
        job_spec["backoffLimit"] = job_spec.get("backoffLimit", 0)
        job_labels["wandb"] = "launch"
        job_metadata["namespace"] = job_metadata.get("namespace", NAMESPACE)
        job_metadata["name"] = job_metadata.get("name", job_name)
        job["apiVersion"] = "batch/v1"
        job["kind"] = "Job"

        # Apply all nested configs from the bottom up
        pod_metadata["labels"] = pod_labels
        pod_template["metadata"] = pod_metadata
        container["name"] = container.get("name", "wandb-container-build")
        container["image"] = container.get("image", self.image)
        container["volumeMounts"] = volume_mounts
        container["env"] = env
        pod_spec["containers"] = [container]
        pod_spec["volumes"] = volumes
        pod_template["spec"] = pod_spec
        job_spec["template"] = pod_template
        job_metadata["labels"] = job_labels
        job["metadata"] = job_metadata
        job["spec"] = job_spec
        return job
