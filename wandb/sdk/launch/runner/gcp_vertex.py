import os
import json
import subprocess
from typing import Any, Dict, List, Optional
import datetime
import yaml

from six.moves import shlex_quote

import wandb
from wandb.sdk.launch.docker import validate_docker_installation
from wandb.errors import CommError, LaunchError
from wandb.apis.internal import Api

from google.cloud import aiplatform

from .._project_spec import (
    DEFAULT_LAUNCH_METADATA_PATH,
    get_entry_point_command,
    LaunchProject,
)
from ..docker import (
    build_docker_image_if_needed,
    construct_gcp_image_uri,
    docker_image_exists,
    docker_image_inspect,
    generate_docker_base_image,
    pull_docker_image,
    validate_docker_installation,
)
from .abstract import AbstractRun, AbstractRunner, Status
from ..utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)


class VertexSubmittedRun(AbstractRun):
    def __init__(self, model) -> None:
        self._model = model

    @property
    def id(self) -> int:
        pass

    def wait(self) -> bool:
        pass

    def get_status(self) -> Status:
        # todo: only sync for now so always finished
        return Status("finished")

    def cancel(self) -> None:
        pass


class VertexRunner(AbstractRunner):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)


    def run(self, launch_project: LaunchProject) -> Optional[AbstractRun]:
        resource_args = launch_project.resource_args
        gcp_config = get_gcp_config(resource_args.get("gcp_config") or "default")
        gcp_project = resource_args.get("gcp_project") or gcp_config['properties']['core']['project']
        gcp_zone = resource_args.get("gcp_region") or gcp_config['properties'].get('compute', {}).get('zone')
        gcp_region = '-'.join(gcp_zone.split('-')[:2])
        if not gcp_region:
            raise LaunchError("GCP region not set. You can specify a region with --resource-arg gcp-region=<region> or a config with --resource-arg gcp-config=<config name>, otherwise uses region from GCP default config.")
        gcp_staging_bucket = resource_args.get("gcp_staging_bucket")
        if not gcp_staging_bucket:
            raise LaunchError("Vertex requires a staging bucket for training and dependency packages in the same region as compute. You can specify a bucket with --resource-arg gcp-staging-bucket=<bucket>.")
        gcp_artifact_repo = resource_args.get("gcp_artifact_repo")
        if not gcp_artifact_repo:
            raise LaunchError("Vertex requires an Artifact Registry repository for the Docker image. You can specify a repo with --resource-arg gcp-artifact-repo=<repo>.")
        gcp_docker_host = resource_args.get("gcp_docker_host") or "{region}-docker.pkg.dev".format(gcp_region)


        aiplatform.init(project=gcp_project, location=gcp_region, staging_bucket=gcp_staging_bucket)


        validate_docker_installation()
        synchronous: bool = self.backend_config[PROJECT_SYNCHRONOUS]
        docker_args: Dict[str, Any] = self.backend_config[PROJECT_DOCKER_ARGS]

        entry_point = launch_project.get_single_entry_point()

        entry_cmd = entry_point.command
        copy_code = True
        if launch_project.docker_image:
            pull_docker_image(launch_project.docker_image)
            copy_code = False
        else:
            # TODO: potentially pull the base_image
            if not docker_image_exists(launch_project.base_image):
                if generate_docker_base_image(launch_project, entry_cmd) is None:
                    raise LaunchError("Unable to build base image")
            else:
                wandb.termlog(
                    "Using existing base image: {}".format(launch_project.base_image)
                )

        command_args = []

        container_inspect = docker_image_inspect(launch_project.base_image)
        container_workdir = container_inspect["ContainerConfig"].get("WorkingDir", "/")
        container_env: List[str] = container_inspect["ContainerConfig"]["Env"]

        if launch_project.docker_image is None or launch_project.build_image:
            image_uri = construct_gcp_image_uri(
                launch_project,
                gcp_artifact_repo,
                gcp_project,
                gcp_docker_host,
            )
            image = build_docker_image_if_needed(
                launch_project=launch_project,
                api=self._api,
                copy_code=copy_code,
                workdir=container_workdir,
                container_env=container_env,
                runner_type='gcp-vertex',
                image_uri=image_uri
            )
        else:
            image = launch_project.docker_image

        # push to artifact registry
        subprocess.run(['docker', 'push', image])     # todo: when aws pr is merged, use docker python tooling

        if self.backend_config.get("runQueueItemId"):
            try:
                self._api.ack_run_queue_item(
                    self.backend_config["runQueueItemId"], launch_project.run_id
                )
            except CommError:
                wandb.termerror(
                    "Error acking run queue item. Item lease may have ended or another process may have acked it."
                )
                return None

        with open(
            os.path.join(launch_project.aux_dir, DEFAULT_LAUNCH_METADATA_PATH), "w"
        ) as fp:
            json.dump(
                {
                    **launch_project.launch_spec,
                    "dockerfile_contents": launch_project._dockerfile_contents,
                },
                fp,
            )

        command_args += get_entry_point_command(
            entry_point, launch_project.override_args
        )

        args = [i for p in [["--" + k, str(v)] for k, v in launch_project.override_args.items()] for i in p]

        TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        job = aiplatform.CustomContainerTrainingJob(
            display_name='test_job' + TIMESTAMP,
            container_uri=image,
            # model_serving_container_image_uri=image,
        )

        # can support gcp dataset here
        # Usage with Dataset:

        # ds = aiplatform.TabularDataset(
        # ‘projects/my-project/locations/us-central1/datasets/12345’)

        # job.run(
        # ds, replica_count=1, model_display_name=’my-trained-model’, model_labels={‘key’: ‘value’},

        # )

        # Usage without Dataset:

        # job.run(replica_count=1, model_display_name=’my-trained-model)

        model = job.run(
            # model_display_name='test_model',
            machine_type='n1-standard-4',
            accelerator_count=0,
            replica_count=1,
            args=args,
        )

        # need to figure out what a managed model is
        # todo: this runs sync only
        return VertexSubmittedRun(model)


def run_shell(args):
    return subprocess.run(args, capture_output=True).stdout.decode('utf-8').strip()


def get_gcp_config(config='default'):
    return yaml.safe_load(run_shell(['gcloud', 'config', 'configurations', 'describe', shlex_quote(config)]))