import asyncio
import logging
from typing import Any, Dict, Optional

if False:
    from google.cloud import aiplatform  # type: ignore   # noqa: F401

from wandb.apis.internal import Api
from wandb.util import get_module

from .._project_spec import LaunchProject
from ..environment.gcp_environment import GcpEnvironment
from ..errors import LaunchError
from ..registry.abstract import AbstractRegistry
from ..utils import MAX_ENV_LENGTHS, PROJECT_SYNCHRONOUS, event_loop_thread_exec
from .abstract import AbstractRun, AbstractRunner, Status

GCP_CONSOLE_URI = "https://console.cloud.google.com"

_logger = logging.getLogger(__name__)


WANDB_RUN_ID_KEY = "wandb-run-id"


class VertexSubmittedRun(AbstractRun):
    def __init__(self, job: Any) -> None:
        self._job = job

    @property
    def id(self) -> str:
        # numeric ID of the custom training job
        return self._job.name  # type: ignore

    async def get_logs(self) -> Optional[str]:
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
        return f"{GCP_CONSOLE_URI}/vertex-ai/locations/{self.gcp_region}/training/{self.id}?project={self.gcp_project}"

    async def wait(self) -> bool:
        # TODO: run this in a separate thread.
        await self._job.wait()
        return (await self.get_status()).state == "finished"

    async def get_status(self) -> Status:
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

    async def cancel(self) -> None:
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

    async def run(
        self, launch_project: LaunchProject, image_uri: str
    ) -> Optional[AbstractRun]:
        """Run a Vertex job."""
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
            launch_project.override_entrypoint or launch_project.get_job_entry_point()
        )

        # TODO: Set entrypoint in each container
        entry_cmd = []
        if entry_point is not None:
            entry_cmd += entry_point.command
        entry_cmd += launch_project.override_args

        env_vars = launch_project.get_env_vars_dict(
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

            # Add our env vars to user supplied env vars
            env = spec["container_spec"].get("env", [])
            env.extend(
                [{"name": key, "value": value} for key, value in env_vars.items()]
            )
            spec["container_spec"]["env"] = env

        if not spec_args.get("staging_bucket"):
            raise LaunchError(
                "Vertex requires a staging bucket. Please specify a staging bucket "
                "in resource arguments under the key `vertex.spec.staging_bucket`."
            )

        _logger.info("Launching Vertex job...")
        submitted_run = await launch_vertex_job(
            launch_project,
            spec_args,
            run_args,
            self.environment,
            synchronous,
        )
        return submitted_run


async def launch_vertex_job(
    launch_project: LaunchProject,
    spec_args: Dict[str, Any],
    run_args: Dict[str, Any],
    environment: GcpEnvironment,
    synchronous: bool = False,
) -> VertexSubmittedRun:
    try:
        await environment.verify()
        aiplatform = get_module(
            "google.cloud.aiplatform",
            "VertexRunner requires google.cloud.aiplatform to be installed",
        )
        init = event_loop_thread_exec(aiplatform.init)
        await init(
            project=environment.project,
            location=environment.region,
            staging_bucket=spec_args.get("staging_bucket"),
            credentials=await environment.get_credentials(),
        )
        labels = spec_args.get("labels", {})
        labels[WANDB_RUN_ID_KEY] = launch_project.run_id
        job = aiplatform.CustomJob(
            display_name=launch_project.name,
            worker_pool_specs=spec_args.get("worker_pool_specs"),
            base_output_dir=spec_args.get("base_output_dir"),
            encryption_spec_key_name=spec_args.get("encryption_spec_key_name"),
            labels=labels,
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
        run = event_loop_thread_exec(job.run)
        await run(**execution_kwargs, sync=True)
    else:
        submit = event_loop_thread_exec(job.submit)
        await submit(**execution_kwargs)
    submitted_run = VertexSubmittedRun(job)
    interval = 1
    while not getattr(job._gca_resource, "name", None):
        # give time for the gcp job object to be created and named, this should only loop a couple times max
        await asyncio.sleep(interval)
        interval = min(30, interval * 2)
    return submitted_run
