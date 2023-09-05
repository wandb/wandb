import time
from typing import Any, Dict, Optional

if False:
    from google.cloud import aiplatform  # type: ignore   # noqa: F401

from wandb.apis.internal import Api
from wandb.util import get_module

from .._project_spec import LaunchProject, get_entry_point_command
from ..builder.build import get_env_vars_dict
from ..environment.gcp_environment import GcpEnvironment
from ..errors import LaunchError
from ..registry.abstract import AbstractRegistry
from ..utils import MAX_ENV_LENGTHS, PROJECT_SYNCHRONOUS
from .abstract import AbstractRun, AbstractRunner, Status

GCP_CONSOLE_URI = "https://console.cloud.google.com"


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
        # We support setting under gcp-vertex for historical reasons.
        if not resource_args:
            resource_args = full_resource_args.get("gcp-vertex")
        if not resource_args:
            raise LaunchError(
                "No Vertex resource args specified. Specify args via --resource-args with a JSON file or string under top-level key gcp_vertex"
            )

        spec_args = resource_args.get("spec", {})
        run_args = resource_args.get("run", {})

        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]

        entry_point = (
            launch_project.override_entrypoint
            or launch_project.get_single_entry_point()
        )

        # TODO: Set entrypoint in each container
        entry_cmd = get_entry_point_command(entry_point, launch_project.override_args)
        env_vars = get_env_vars_dict(
            launch_project=launch_project,
            api=self._api,
            max_env_length=MAX_ENV_LENGTHS[self.__class__.__name__],
        )

        worker_specs = spec_args.get("worker_pool_specs", [])
        if not worker_specs:
            raise LaunchError(
                "Vertex requires at least one worker pool spec. Please specify "
                "a worker pool spec in resource arguments under the key "
                "`vertex.spec.worker_pool_specs`."
            )

        # TODO: Add entrypoint + args to each worker pool spec
        for spec in worker_specs:
            if not spec.get("container_spec"):
                raise LaunchError(
                    "Vertex requires a container spec for each worker pool spec. "
                    "Please specify a container spec in resource arguments under "
                    "the key `vertex.spec.worker_pool_specs[].container_spec`."
                )
            spec["container_spec"]["command"] = entry_cmd
            spec["container_spec"]["env"] = [
                {"name": k, "value": v} for k, v in env_vars.items()
            ]

        if not spec_args.get("staging_bucket"):
            raise LaunchError(
                "Vertex requires a staging bucket. Please specify a staging bucket "
                "in resource arguments under the key `vertex.spec.staging_bucket`."
            )
        try:
            aiplatform.init(
                project=self.environment.project,
                location=self.environment.region,
                staging_bucket=spec_args.get("staging_bucket"),
                credentials=self.environment.get_credentials(),
            )
            job = aiplatform.CustomJob(
                display_name=launch_project.name,
                worker_pool_specs=spec_args.get("worker_pool_specs"),
                base_output_dir=spec_args.get("base_output_dir"),
                encryption_spec_key_name=spec_args.get("encryption_spec_key_name"),
                labels=spec_args.get("labels", {}),
            )
            execution_kwargs = dict(
                timeout=run_args.get("timeout"),
                service_account=run_args.get("service_account"),
                network=run_args.get("network"),
                enable_web_access=run_args.get("enable_web_access", False),
                experiment=run_args.get("experiment"),
                experiment_run=run_args.get("experiment_run"),
                tensorboard=run_args.get("tensorboard"),
                restart_job_on_worker_restart=run_args.get(
                    "restart_job_on_worker_restart", False
                ),
            )
        # Unclear if there are exceptions that can be thrown where we should
        # retry instead of erroring. For now, just catch all exceptions and they
        # go to the UI for the user to interpret.
        except Exception as e:
            raise LaunchError(f"Failed to create Vertex job: {e}")
        if synchronous:
            job.run(**execution_kwargs, sync=True)
        else:
            job.submit(**execution_kwargs)
        submitted_run = VertexSubmittedRun(job)
        while not getattr(job._gca_resource, "name", None):
            # give time for the gcp job object to be created and named, this should only loop a couple times max
            time.sleep(1)
        return submitted_run
