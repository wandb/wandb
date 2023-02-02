import datetime
import shlex
from typing import Any, Dict, Optional

if False:
    from google.cloud import aiplatform  # type: ignore   # noqa: F401

import yaml

import wandb
from wandb.errors import LaunchError
from wandb.util import get_module

from .._project_spec import LaunchProject, get_entry_point_command
from ..builder.abstract import AbstractBuilder
from ..builder.build import get_env_vars_dict
from ..utils import LOG_PREFIX, PROJECT_DOCKER_ARGS, PROJECT_SYNCHRONOUS, run_shell
from .abstract import AbstractRun, AbstractRunner, Status

GCP_CONSOLE_URI = "https://console.cloud.google.com"


class VertexSubmittedRun(AbstractRun):
    def __init__(self, job: Any) -> None:
        self._job = job

    @property
    def id(self) -> str:
        # numeric ID of the custom training job
        return self._job.name  # type: ignore

    @property
    def name(self) -> str:
        return self._job.display_name  # type: ignore

    @property
    def gcp_region(self) -> str:
        return self._job.location  # type: ignore

    @property
    def gcp_project(self) -> str:
        return self._job.project  # type: ignore

    def get_page_link(self) -> str:
        return "{console_uri}/vertex-ai/locations/{region}/training/{job_id}?project={project}".format(
            console_uri=GCP_CONSOLE_URI,
            region=self.gcp_region,
            job_id=self.id,
            project=self.gcp_project,
        )

    def wait(self) -> bool:
        self._job.wait()
        return self.get_status().state == "finished"

    def get_status(self) -> Status:
        job_state = str(self._job.state)  # extract from type PipelineState
        if job_state == "JobState.JOB_STATE_SUCCEEDED":
            return Status("finished")
        if job_state == "JobState.JOB_STATE_FAILED":
            return Status("failed")
        if job_state == "JobState.JOB_STATE_RUNNING":
            return Status("running")
        # TODO: Handle more job states https://cloud.google.com/vertex-ai/docs/reference/rest/v1/JobState
        # TODO: Job being in an unknown state needs to be dealt with loudly
        return Status("unknown")

    def cancel(self) -> None:
        self._job.cancel()


class VertexRunner(AbstractRunner):
    """Runner class, uses a project to create a VertexSubmittedRun"""

    def run(
        self,
        launch_project: LaunchProject,
        builder: AbstractBuilder,
        registry_config: Dict[str, Any],
    ) -> Optional[AbstractRun]:
        aiplatform = get_module(  # noqa: F811
            "google.cloud.aiplatform",
            "VertexRunner requires google.cloud.aiplatform to be installed",
        )
        resource_args = launch_project.resource_args.get("gcp_vertex")
        if not resource_args:
            raise LaunchError(
                "No Vertex resource args specified. Specify args via --resource-args with a JSON file or string under top-level key gcp_vertex"
            )
        gcp_config = get_gcp_config(resource_args.get("gcp_config") or "default")
        gcp_project = (
            resource_args.get("gcp_project")
            or gcp_config["properties"]["core"]["project"]
        )
        gcp_region = resolve_gcp_region(resource_args, gcp_config, registry_config)
        gcp_machine_type = resource_args.get("machine_type") or "n1-standard-4"
        gcp_accelerator_type = (
            resource_args.get("accelerator_type") or "ACCELERATOR_TYPE_UNSPECIFIED"
        )
        gcp_accelerator_count = int(resource_args.get("accelerator_count") or 0)
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        gcp_training_job_name = resource_args.get(
            "job_name"
        ) or "{project}_{time}".format(
            project=launch_project.target_project, time=timestamp
        )
        service_account = resource_args.get("service_account")
        tensorboard = resource_args.get("tensorboard")
        gcp_staging_bucket = resource_args.get("staging_bucket")
        if not gcp_staging_bucket:
            raise LaunchError(
                "Vertex requires a staging bucket for training and dependency "
                "packages in the same region as compute. Specify a bucket under "
                "key staging_bucket."
            )
        aiplatform.init(
            project=gcp_project, location=gcp_region, staging_bucket=gcp_staging_bucket
        )
        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]
        docker_args: Dict[str, Any] = self.backend_config[PROJECT_DOCKER_ARGS]
        if docker_args and list(docker_args) != ["docker_image"]:
            wandb.termwarn(
                f"{LOG_PREFIX}Docker args are not supported for GCP. Not using docker args."
            )
        entry_point = launch_project.get_single_entry_point()
        if launch_project.docker_image:
            # Use premade docker image uri
            image_uri = launch_project.docker_image
        else:
            # If docker image is not specified, build it
            repository = resolve_artifact_repo(
                resource_args, registry_config, gcp_project, gcp_region
            )
            assert entry_point is not None
            image_uri = builder.build_image(
                launch_project,
                repository,
                entry_point,
                docker_args,
            )
        if not self.ack_run_queue_item(launch_project):
            return None
        # TODO: how to handle this?
        entry_cmd = get_entry_point_command(entry_point, launch_project.override_args)
        worker_pool_specs = [
            {
                "machine_spec": {
                    "machine_type": gcp_machine_type,
                    "accelerator_type": gcp_accelerator_type,
                    "accelerator_count": gcp_accelerator_count,
                },
                "replica_count": 1,
                "container_spec": {
                    "image_uri": image_uri,
                    "command": entry_cmd,
                    "env": [
                        {"name": k, "value": v}
                        for k, v in get_env_vars_dict(launch_project, self._api).items()
                    ],
                },
            }
        ]
        job = aiplatform.CustomJob(
            display_name=gcp_training_job_name, worker_pool_specs=worker_pool_specs
        )
        submitted_run = VertexSubmittedRun(job)
        wandb.termlog(
            f"{LOG_PREFIX}Running training job {gcp_training_job_name} on {gcp_machine_type}."
        )
        if synchronous:
            job.run(
                service_account=service_account, tensorboard=tensorboard, sync=False
            )
        else:
            # TODO: this submit command is only in aiplatform >=1.20 which needs
            # to be flagged or pinned somewhere
            job.submit(
                service_account=service_account,
                tensorboard=tensorboard,
            )
        job.wait_for_resource_creation()
        wandb.termlog(
            f"{LOG_PREFIX}View your job status and logs at {submitted_run.get_page_link()}."
        )
        if synchronous:
            submitted_run.wait()
        return submitted_run


def get_gcp_config(config: str = "default") -> Any:
    try:
        config_yaml = run_shell(
            ["gcloud", "config", "configurations", "describe", shlex.quote(config)]
        )[0]
        return yaml.safe_load(config_yaml)
    except Exception as e:
        wandb.termwarn(f"{LOG_PREFIX}Unable to read gcloud config for {config}")
        wandb.termwarn(f"{LOG_PREFIX}Error: {e}")

    # If we can't read the config, return an empty dict
    return {"properties": {}}


def resolve_gcp_region(resource_args, gcp_config, registry_config):
    """Resolve the GCP region from resource args, gcp config, and registry config.

    Args:
        resource_args: The resource args passed to the backend.
        gcp_config: The gcloud config pulled from the local environment.
        registry_config: The agent level registry config.

    Returns:
        The GCP region to use for compute and storage.

    Raises:
        LaunchError: If the region cannot be resolved.
    """
    gcp_zone = resource_args.get("gcp_region") or (
        gcp_config.get("properties", {}).get("compute", {}).get("zone")
    )
    if not gcp_zone:
        registry_region = registry_config.get("region")
        if registry_region:
            # TODO: validate the region is valid
            return registry_region
        raise LaunchError(
            "Vertex requires a region for compute. Specify a region under key gcp_region."
        )
    gcp_region = "-".join(gcp_zone.split("-")[:2])
    return gcp_region


def resolve_artifact_repo(
    resource_args: dict, registry_config: dict, gcp_project: str, gcp_region: str
) -> str:
    """Resolve the Artifact Registry repo from resource args and registry config.

    Args:
        resource_args: The resource args passed to the backend.
        registry_config: The registry config from gcloud.
        gcp_project: The gcp project, in case the image uri needs to be inferred.
        gcp_region: The default region in case the docker host needs to be inferred.

    Returns:
        The resolved repo as a str.

    Raises:
        LaunchError: If repo is not set in either resource args or registry config.
    """

    # If a full repo uri is specified, use that
    registry_repo = registry_config.get("url")
    if registry_repo:
        # TODO: Do some kind of validation that this repo is valid
        return registry_repo

    # Otherwise, use the repo specified in resource args
    docker_host = resolve_docker_host(resource_args, gcp_region)
    repo_name = resource_args.get("artifact_repo")
    if not repo_name:
        raise LaunchError(
            "Vertex requires that you specify an Artifact Registry repository. "
            "Please specify a repo in your resource args under key artifact_repo or "
            "in your launch agent registry config under key url."
        )
    repository = "/".join([docker_host, gcp_project, repo_name])
    # TODO: verify that this repo is valid
    return repository


def resolve_docker_host(resource_args, gcp_region):
    """Resolve the docker host from resource args and gcloud configuration."""
    resource_host = resource_args.get("docker_host")
    default_host = f"{gcp_region}-docker.pkg.dev"
    host = resource_host or default_host
    # TODO: Validate that the host is valid
    return host
