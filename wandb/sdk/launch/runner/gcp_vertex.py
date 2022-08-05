import datetime
import os
import shlex
import time
from typing import Any, Dict, Optional

if False:
    from google.cloud import aiplatform  # type: ignore   # noqa: F401
import wandb
from wandb.errors import LaunchError
from wandb.util import get_module
import yaml

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import get_entry_point_command, LaunchProject
from ..builder.abstract import AbstractBuilder
from ..builder.build import (
    construct_gcp_registry_uri,
    get_env_vars_dict,
)
from ..utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
    run_shell,
)

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
        if job_state == "PipelineState.PIPELINE_STATE_SUCCEEDED":
            return Status("finished")
        if job_state == "PipelineState.PIPELINE_STATE_FAILED":
            return Status("failed")
        if job_state == "PipelineState.PIPELINE_STATE_RUNNING":
            return Status("running")
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
        gcp_zone = resource_args.get("gcp_region") or gcp_config["properties"].get(
            "compute", {}
        ).get("zone")
        gcp_region = "-".join(gcp_zone.split("-")[:2])
        gcp_staging_bucket = resource_args.get("staging_bucket")
        if not gcp_staging_bucket:
            raise LaunchError(
                "Vertex requires a staging bucket for training and dependency packages in the same region as compute. Specify a bucket under key staging_bucket."
            )
        gcp_artifact_repo = resource_args.get("artifact_repo")
        if not gcp_artifact_repo:
            raise LaunchError(
                "Vertex requires an Artifact Registry repository for the Docker image. Specify a repo under key artifact_repo."
            )
        gcp_docker_host = (
            resource_args.get("docker_host") or f"{gcp_region}-docker.pkg.dev"
        )
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

        aiplatform.init(
            project=gcp_project, location=gcp_region, staging_bucket=gcp_staging_bucket
        )
        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]
        docker_args: Dict[str, Any] = self.backend_config[PROJECT_DOCKER_ARGS]
        if docker_args and list(docker_args) != ["docker_image"]:
            wandb.termwarn(
                "Docker args are not supported for GCP. Not using docker args"
            )

        entry_point = launch_project.get_single_entry_point()

        if launch_project.docker_image:
            image_uri = launch_project.docker_image
        else:

            repository = construct_gcp_registry_uri(
                gcp_artifact_repo,
                gcp_project,
                gcp_docker_host,
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

        # todo: support gcp dataset?

        wandb.termlog(
            "Running training job {name} on {compute}.".format(
                name=gcp_training_job_name, compute=gcp_machine_type
            )
        )

        # when sync is True, vertex blocks the main thread on job completion. when False, vertex returns a Future
        # on this thread but continues to block the process on another thread. always set sync=False so we can get
        # the job info (dependent on job._gca_resource)
        job.run(service_account=service_account, tensorboard=tensorboard, sync=False)

        while not getattr(job._gca_resource, "name", None):
            # give time for the gcp job object to be created and named, this should only loop a couple times max
            time.sleep(1)

        wandb.termlog(
            "View your job status and logs at {url}.".format(
                url=submitted_run.get_page_link()
            )
        )

        # hacky: if user doesn't want blocking behavior, kill both main thread and the background thread. job continues
        # to run remotely. this obviously doesn't work if we need to do some sort of postprocessing after this run fn
        if not synchronous:
            os._exit(0)

        return submitted_run


def get_gcp_config(config: str = "default") -> Any:
    return yaml.safe_load(
        run_shell(
            ["gcloud", "config", "configurations", "describe", shlex.quote(config)]
        )[0]
    )


def exists_on_gcp(image: str, tag: str) -> bool:
    out, err = run_shell(
        [
            "gcloud",
            "artifacts",
            "docker",
            "images",
            "list",
            shlex.quote(image),
            "--include-tags",
            f"--filter=tags:{shlex.quote(tag)}",
        ]
    )
    return tag in out and "sha256:" in out
