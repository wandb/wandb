import asyncio
import base64
import json
import logging
import os
import tarfile
import tempfile
import time
import traceback
from typing import Optional

import wandb
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.builder.build import registry_from_uri
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.environment.azure_environment import AzureEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.registry.azure_container_registry import AzureContainerRegistry
from wandb.sdk.launch.registry.elastic_container_registry import (
    ElasticContainerRegistry,
)
from wandb.sdk.launch.registry.google_artifact_registry import GoogleArtifactRegistry
from wandb.util import get_module

from .._project_spec import (
    EntryPoint,
    LaunchProject,
    create_metadata_file,
    get_entry_point_command,
)
from ..errors import LaunchError
from ..utils import (
    LOG_PREFIX,
    get_kube_context_and_api_client,
    sanitize_wandb_api_key,
    warn_failed_packages_from_build_logs,
)
from .build import (
    _WANDB_DOCKERFILE_NAME,
    _create_docker_build_ctx,
    generate_dockerfile,
    image_tag_from_dockerfile_and_source,
)

get_module(
    "kubernetes_asyncio",
    required="Kaniko builder requires the kubernetes_asyncio package. Please install it with `pip install wandb[launch]`.",
)

import kubernetes_asyncio as kubernetes  # type: ignore # noqa: E402
from kubernetes_asyncio import client  # noqa: E402

_logger = logging.getLogger(__name__)

_DEFAULT_BUILD_TIMEOUT_SECS = 1800  # 30 minute build timeout

SERVICE_ACCOUNT_NAME = os.environ.get("WANDB_LAUNCH_SERVICE_ACCOUNT_NAME", "default")

if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/namespace"):
    with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as f:
        NAMESPACE = f.read().strip()
else:
    NAMESPACE = "wandb"


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
        if build_context_store is None:
            raise LaunchError(
                "You are required to specify an external build "
                "context store for Kaniko builds. Please specify a  storage url "
                "in the 'build-context-store' field of your builder config."
            )
        self.environment = environment
        self.registry = registry
        self.build_job_name = build_job_name
        self.build_context_store = build_context_store.rstrip("/")
        self.secret_name = secret_name
        self.secret_key = secret_key
        self.image = image

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
        build_context_store = config.get("build-context-store")
        if build_context_store is None:
            raise LaunchError(
                "You are required to specify an external build "
                "context store for Kaniko builds. Please specify a  "
                "storage url in the 'build_context_store' field of your builder config."
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
        return cls(
            environment,
            registry,
            build_context_store=build_context_store,
            build_job_name=build_job_name,
            secret_name=secret_name,
            secret_key=secret_key,
            image=kaniko_image,
        )

    async def verify(self) -> None:
        """Verify that the builder config is valid.

        Raises:
            LaunchError: If the builder config is invalid.
        """
        if self.environment is None:
            raise LaunchError("No environment specified for Kaniko build.")
        await self.environment.verify_storage_uri(self.build_context_store)

    def login(self) -> None:
        """Login to the registry."""
        pass

    async def _create_docker_ecr_config_map(
        self, job_name: str, corev1_client: client.CoreV1Api, repository: str
    ) -> None:
        if self.registry is None:
            raise LaunchError("No registry specified for Kaniko build.")
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
        destination = f"{self.build_context_store}/{run_id}.tgz"
        if self.environment is None:
            raise LaunchError("No environment specified for Kaniko build.")
        await self.environment.upload_file(context_file.name, destination)
        return destination

    async def build_image(
        self,
        launch_project: LaunchProject,
        entrypoint: EntryPoint,
        job_tracker: Optional[JobAndRunStatusTracker] = None,
    ) -> str:
        await self.verify()
        # TODO: this should probably throw an error if the registry is a local registry
        if not self.registry:
            raise LaunchError("No registry specified for Kaniko build.")
        # kaniko builder doesn't seem to work with a custom user id, need more investigation
        dockerfile_str = generate_dockerfile(
            launch_project=launch_project,
            entry_point=entrypoint,
            runner_type=launch_project.resource,
            builder_type="kaniko",
            dockerfile=launch_project.override_dockerfile,
        )
        image_tag = image_tag_from_dockerfile_and_source(launch_project, dockerfile_str)
        repo_uri = await self.registry.get_repo_uri()
        image_uri = repo_uri + ":" + image_tag

        if (
            not launch_project.build_required()
            and await self.registry.check_image_exists(image_uri)
        ):
            return image_uri

        _logger.info(f"Building image {image_uri}...")

        entry_cmd = " ".join(
            get_entry_point_command(entrypoint, launch_project.override_args)
        )

        create_metadata_file(
            launch_project,
            image_uri,
            sanitize_wandb_api_key(entry_cmd),
            sanitize_wandb_api_key(dockerfile_str),
        )
        context_path = _create_docker_build_ctx(launch_project, dockerfile_str)
        run_id = launch_project.run_id

        _, api_client = await get_kube_context_and_api_client(
            kubernetes, launch_project.resource_args
        )
        # TODO: use same client as kuberentes_runner.py
        batch_v1 = client.BatchV1Api(api_client)
        core_v1 = client.CoreV1Api(api_client)

        build_job_name = f"{self.build_job_name}-{run_id}"

        build_context = await self._upload_build_context(run_id, context_path)
        build_job = await self._create_kaniko_job(
            build_job_name, repo_uri, image_uri, build_context, core_v1
        )
        wandb.termlog(f"{LOG_PREFIX}Created kaniko job {build_job_name}")

        try:
            if isinstance(self.registry, AzureContainerRegistry):
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
            await batch_v1.create_namespaced_job(NAMESPACE, build_job)

            # wait for double the job deadline since it might take time to schedule
            if not await _wait_for_completion(
                batch_v1, build_job_name, 3 * _DEFAULT_BUILD_TIMEOUT_SECS
            ):
                if job_tracker:
                    job_tracker.set_err_stage("build")
                raise Exception(f"Failed to build image in kaniko for job {run_id}")
            try:
                pods_from_job = await core_v1.list_namespaced_pod(
                    namespace=NAMESPACE, label_selector=f"job-name={build_job_name}"
                )
                if len(pods_from_job.items) != 1:
                    raise Exception(
                        f"Expected 1 pod for job {build_job_name}, found {len(pods_from_job.items)}"
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
            raise e
        finally:
            wandb.termlog(f"{LOG_PREFIX}Cleaning up resources")
            try:
                if isinstance(self.registry, AzureContainerRegistry):
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
    ) -> "client.V1Job":
        env = []
        volume_mounts = []
        volumes = []
        if bool(self.secret_name) != bool(self.secret_key):
            raise LaunchError(
                "Both secret_name and secret_key or neither must be specified "
                "for kaniko build. You provided only one of them."
            )
        if isinstance(self.registry, ElasticContainerRegistry):
            env += [
                client.V1EnvVar(
                    name="AWS_REGION",
                    value=self.registry.region,
                )
            ]
        # TODO: Refactor all of this environment/registry
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
            env += [
                client.V1EnvVar(
                    name="AZURE_STORAGE_ACCESS_KEY",
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name="azure-storage-access-key",
                            key="password",
                        )
                    ),
                )
            ]

        if self.secret_name and self.secret_key:
            volumes += [
                client.V1Volume(
                    name="docker-config",
                    config_map=client.V1ConfigMapVolumeSource(
                        name=f"docker-config-{job_name}",
                    ),
                ),
            ]
            volume_mounts += [
                client.V1VolumeMount(
                    name="docker-config", mount_path="/kaniko/.docker/"
                ),
            ]
            # TODO: I don't like conditioning on the registry type here. As a
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
                env += [
                    client.V1EnvVar(
                        name="GOOGLE_APPLICATION_CREDENTIALS",
                        value="/kaniko/.config/gcloud/config.json",
                    )
                ]
            else:
                raise LaunchError(
                    f"Registry type {type(self.registry)} not supported by kaniko"
                )
            volume_mounts += [
                client.V1VolumeMount(
                    name=self.secret_name,
                    mount_path=mount_path,
                    read_only=True,
                )
            ]
            volumes += [
                client.V1Volume(
                    name=self.secret_name,
                    secret=client.V1SecretVolumeSource(
                        secret_name=self.secret_name,
                        items=[client.V1KeyToPath(key=self.secret_key, path=key)],
                    ),
                )
            ]
        if isinstance(self.registry, AzureContainerRegistry):
            # ADd the docker config map
            volume_mounts += [
                client.V1VolumeMount(
                    name="docker-config", mount_path="/kaniko/.docker/"
                ),
            ]
            volumes += [
                client.V1Volume(
                    name="docker-config",
                    config_map=client.V1ConfigMapVolumeSource(
                        name=f"docker-config-{job_name}",
                    ),
                ),
            ]
        # Kaniko doesn't want https:// at the begining of the image tag.
        destination = image_tag
        if destination.startswith("https://"):
            destination = destination.replace("https://", "")
        args = [
            f"--context={build_context_path}",
            f"--dockerfile={_WANDB_DOCKERFILE_NAME}",
            f"--destination={destination}",
            "--cache=true",
            f"--cache-repo={repository.replace('https://', '')}",
            "--snapshotMode=redo",
            "--compressed-caching=false",
        ]
        container = client.V1Container(
            name="wandb-container-build",
            image=self.image,
            args=args,
            volume_mounts=volume_mounts,
            env=env if env else None,
        )
        # Create and configure a spec section
        labels = {"wandb": "launch"}
        # This annotation is required to enable azure workload identity.
        if isinstance(self.registry, AzureContainerRegistry):
            labels["azure.workload.identity/use"] = "true"
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels=labels),
            spec=client.V1PodSpec(
                restart_policy="Never",
                active_deadline_seconds=_DEFAULT_BUILD_TIMEOUT_SECS,
                containers=[container],
                volumes=volumes,
                service_account_name=SERVICE_ACCOUNT_NAME,
            ),
        )
        # Create the specification of job
        spec = client.V1JobSpec(template=template, backoff_limit=0)
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name, namespace=NAMESPACE, labels={"wandb": "launch"}
            ),
            spec=spec,
        )
        return job
