import base64
import json
import logging
import tarfile
import tempfile
import time
from typing import Optional

import wandb
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
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
from ..utils import (
    LOG_PREFIX,
    LaunchError,
    get_kube_context_and_api_client,
    sanitize_wandb_api_key,
    warn_failed_packages_from_build_logs,
)
from .build import (
    _create_docker_build_ctx,
    generate_dockerfile,
    image_tag_from_dockerfile_and_source,
)

get_module(
    "kubernetes",
    required="Kaniko builder requires the kubernetes package. Please install it with `pip install wandb[launch]`.",
)

import kubernetes  # type: ignore # noqa: E402
from kubernetes import client  # noqa: E402

_logger = logging.getLogger(__name__)

_DEFAULT_BUILD_TIMEOUT_SECS = 1800  # 30 minute build timeout


def _wait_for_completion(
    batch_client: client.BatchV1Api, job_name: str, deadline_secs: Optional[int] = None
) -> bool:
    start_time = time.time()
    while True:
        job = batch_client.read_namespaced_job_status(job_name, "wandb")
        if job.status.succeeded is not None and job.status.succeeded >= 1:
            return True
        elif job.status.failed is not None and job.status.failed >= 1:
            wandb.termerror(f"{LOG_PREFIX}Build job {job.status.failed} failed {job}")
            return False
        wandb.termlog(f"{LOG_PREFIX}Waiting for build job to complete...")
        if deadline_secs is not None and time.time() - start_time > deadline_secs:
            return False

        time.sleep(5)


class KanikoBuilder(AbstractBuilder):
    """Builds a docker image for a project using Kaniko."""

    type = "kaniko"

    build_job_name: str
    build_context_store: str
    secret_name: Optional[str]
    secret_key: Optional[str]

    def __init__(
        self,
        environment: AbstractEnvironment,
        registry: AbstractRegistry,
        build_job_name: str = "wandb-launch-container-build",
        build_context_store: str = "",
        secret_name: str = "",
        secret_key: str = "",
        verify: bool = True,
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
        if verify:
            self.verify()

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
        return cls(
            environment,
            registry,
            build_context_store=build_context_store,
            build_job_name=build_job_name,
            secret_name=secret_name,
            secret_key=secret_key,
            verify=verify,
        )

    def verify(self) -> None:
        """Verify that the builder config is valid.

        Raises:
            LaunchError: If the builder config is invalid.
        """
        if self.environment is None:
            raise LaunchError("No environment specified for Kaniko build.")
        self.environment.verify_storage_uri(self.build_context_store)

    def login(self) -> None:
        """Login to the registry."""
        pass

    def _create_docker_ecr_config_map(
        self, job_name: str, corev1_client: client.CoreV1Api, repository: str
    ) -> None:
        if self.registry is None:
            raise LaunchError("No registry specified for Kaniko build.")
        username, password = self.registry.get_username_password()
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode("utf-8")
        ecr_config_map = client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=client.V1ObjectMeta(
                name=f"docker-config-{job_name}",
                namespace="wandb",
            ),
            data={
                "config.json": json.dumps(
                    {"auths": {f"{self.registry.get_repo_uri()}": {"auth": encoded}}}
                )
            },
            immutable=True,
        )
        corev1_client.create_namespaced_config_map("wandb", ecr_config_map)

    def _delete_docker_ecr_config_map(
        self, job_name: str, client: client.CoreV1Api
    ) -> None:
        if self.secret_name:
            client.delete_namespaced_config_map(f"docker-config-{job_name}", "wandb")

    def _upload_build_context(self, run_id: str, context_path: str) -> str:
        # creat a tar archive of the build context and upload it to s3
        context_file = tempfile.NamedTemporaryFile(delete=False)
        with tarfile.TarFile.open(fileobj=context_file, mode="w:gz") as context_tgz:
            context_tgz.add(context_path, arcname=".")
        context_file.close()
        destination = f"{self.build_context_store}/{run_id}.tgz"
        if self.environment is None:
            raise LaunchError("No environment specified for Kaniko build.")
        self.environment.upload_file(context_file.name, destination)
        return destination

    def build_image(
        self,
        launch_project: LaunchProject,
        entrypoint: EntryPoint,
    ) -> str:
        # TODO: this should probably throw an error if the registry is a local registry
        if not self.registry:
            raise LaunchError("No registry specified for Kaniko build.")
        # kaniko builder doesn't seem to work with a custom user id, need more investigation
        dockerfile_str = generate_dockerfile(
            launch_project, entrypoint, launch_project.resource, "kaniko"
        )
        image_tag = image_tag_from_dockerfile_and_source(launch_project, dockerfile_str)
        repo_uri = self.registry.get_repo_uri()
        image_uri = repo_uri + ":" + image_tag

        if not launch_project.build_required() and self.registry.check_image_exists(
            image_uri
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

        _, api_client = get_kube_context_and_api_client(
            kubernetes, launch_project.resource_args
        )
        build_job_name = f"{self.build_job_name}-{run_id}"

        build_context = self._upload_build_context(run_id, context_path)
        build_job = self._create_kaniko_job(
            build_job_name,
            repo_uri,
            image_uri,
            build_context,
        )
        wandb.termlog(f"{LOG_PREFIX}Created kaniko job {build_job_name}")

        # TODO: use same client as kuberentes.py
        batch_v1 = client.BatchV1Api(api_client)
        core_v1 = client.CoreV1Api(api_client)

        try:
            # core_v1.create_namespaced_config_map("wandb", dockerfile_config_map)
            if self.secret_name:
                self._create_docker_ecr_config_map(build_job_name, core_v1, repo_uri)
            batch_v1.create_namespaced_job("wandb", build_job)

            # wait for double the job deadline since it might take time to schedule
            if not _wait_for_completion(
                batch_v1, build_job_name, 3 * _DEFAULT_BUILD_TIMEOUT_SECS
            ):
                raise Exception(f"Failed to build image in kaniko for job {run_id}")
            try:
                logs = batch_v1.read_namespaced_job_log(build_job_name, "wandb")
                warn_failed_packages_from_build_logs(logs, image_uri)
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
                # should we clean up the s3 build contexts? can set bucket level policy to auto deletion
                # core_v1.delete_namespaced_config_map(config_map_name, "wandb")
                if self.secret_name:
                    self._delete_docker_ecr_config_map(build_job_name, core_v1)
                batch_v1.delete_namespaced_job(build_job_name, "wandb")
            except Exception as e:
                raise LaunchError(f"Exception during Kubernetes resource clean up {e}")

        return image_uri

    def _create_kaniko_job(
        self,
        job_name: str,
        repository: str,
        image_tag: str,
        build_context_path: str,
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
                    value=self.registry.environment.region,
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

        args = [
            f"--context={build_context_path}",
            "--dockerfile=Dockerfile.wandb-autogenerated",
            f"--destination={image_tag}",
            "--cache=true",
            f"--cache-repo={repository}",
            "--snapshotMode=redo",
            "--compressed-caching=false",
        ]
        container = client.V1Container(
            name="wandb-container-build",
            image="gcr.io/kaniko-project/executor:v1.8.0",
            args=args,
            volume_mounts=volume_mounts,
            env=env if env else None,
        )
        # Create and configure a spec section
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"wandb": "launch"}),
            spec=client.V1PodSpec(
                restart_policy="Never",
                active_deadline_seconds=_DEFAULT_BUILD_TIMEOUT_SECS,
                containers=[container],
                volumes=volumes,
            ),
        )
        # Create the specification of job
        spec = client.V1JobSpec(template=template, backoff_limit=1)
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name, namespace="wandb", labels={"wandb": "launch"}
            ),
            spec=spec,
        )
        return job
