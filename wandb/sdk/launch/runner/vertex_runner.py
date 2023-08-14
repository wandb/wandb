import datetime
import logging
import time
from typing import Any, Dict, Optional

if False:
    from google.cloud import aiplatform  # type: ignore   # noqa: F401

import yaml

import wandb
from wandb.apis.internal import Api
from wandb.util import get_module

from .._project_spec import LaunchProject, get_entry_point_command
from ..builder.build import get_env_vars_dict
from ..environment.gcp_environment import GcpEnvironment
from ..errors import LaunchError
from ..registry.abstract import AbstractRegistry
from ..utils import LOG_PREFIX, MAX_ENV_LENGTHS, PROJECT_SYNCHRONOUS
from .abstract import AbstractRun, AbstractRunner, Status

GCP_CONSOLE_URI = "https://console.cloud.google.com"

_logger = logging.getLogger(__name__)


class VertexSubmittedRun(AbstractRun):
    def __init__(self, job: Any) -> None:
        self._job = job

    @property
    def id(self) -> str:
        # numeric ID of the custom training job
        return self._job.name  # type: ignore

    def get_logs(self) -> Optional[str]:
        # TODO: implement
        return None

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
        if job_state == "JobState.JOB_STATE_PENDING":
            return Status("starting")
        return Status("unknown")

    def cancel(self) -> None:
        self._job.cancel()


class VertexRunner(AbstractRunner):
    """Runner class, uses a project to create a VertexSubmittedRun."""

    def __init__(
        self,
        api: Api,
        backend_config: Dict[str, Any],
        environment: GcpEnvironment,
        registry: AbstractRegistry,
    ) -> None:
        """Initialize a VertexRunner instance."""
        super().__init__(api, backend_config)
        self.environment = environment
        self.registry = registry

    def run(
        self, launch_project: LaunchProject, image_uri: str
    ) -> Optional[AbstractRun]:
        """Run a Vertex job."""
        aiplatform = get_module(  # noqa: F811
            "google.cloud.aiplatform",
            "VertexRunner requires google.cloud.aiplatform to be installed",
        )
        full_resource_args = launch_project.fill_macros(image_uri)
        resource_args = full_resource_args.get("vertex")
        if not resource_args:
            resource_args = full_resource_args.get("gcp-vertex")
        if not resource_args:
            raise LaunchError(
                "No Vertex resource args specified. Specify args via --resource-args with a JSON file or string under top-level key gcp_vertex"
            )
        gcp_staging_bucket = resource_args.get("staging_bucket")
        if not gcp_staging_bucket:
            raise LaunchError(
                "Vertex requires a staging bucket for training and dependency packages in the same region as compute. Specify a bucket under key staging_bucket."
            )
        gcp_machine_type = resource_args.get("machine_type") or "n1-standard-4"
        gcp_accelerator_type = (
            resource_args.get("accelerator_type") or "ACCELERATOR_TYPE_UNSPECIFIED"
        )
        gcp_accelerator_count = int(resource_args.get("accelerator_count") or 0)
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        gcp_training_job_name = (
            resource_args.get("job_name")
            or f"{launch_project.target_project}_{timestamp}"
        )
        service_account = resource_args.get("service_account")
        tensorboard = resource_args.get("tensorboard")
        aiplatform.init(
            project=self.environment.project,
            location=self.environment.region,
            staging_bucket=gcp_staging_bucket,
        )
        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]

        entry_point = (
            launch_project.override_entrypoint
            or launch_project.get_single_entry_point()
        )

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
                        for k, v in get_env_vars_dict(
                            launch_project,
                            self._api,
                            MAX_ENV_LENGTHS[self.__class__.__name__],
                        ).items()
                    ],
                },
            }
        ]

        job = aiplatform.CustomJob(
            display_name=gcp_training_job_name, worker_pool_specs=worker_pool_specs
        )

        wandb.termlog(
            f"{LOG_PREFIX}Running training job {gcp_training_job_name} on {gcp_machine_type}."
        )

        if synchronous:
            job.run(service_account=service_account, tensorboard=tensorboard, sync=True)
        else:
            job.submit(
                service_account=service_account,
                tensorboard=tensorboard,
            )

        submitted_run = VertexSubmittedRun(job)

        while not getattr(job._gca_resource, "name", None):
            # give time for the gcp job object to be created and named, this should only loop a couple times max
            time.sleep(1)

        wandb.termlog(
            f"{LOG_PREFIX}View your job status and logs at {submitted_run.get_page_link()}."
        )
        return submitted_run
