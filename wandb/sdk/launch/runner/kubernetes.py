import datetime
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from kubernetes import client, config, watch   # @@@ change to conditional import
from six.moves import shlex_quote
import wandb
import wandb.docker as docker
from wandb.errors import LaunchError
from wandb.util import get_module
import yaml

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import LaunchProject
from ..docker import (
    construct_local_image_uri,
    generate_docker_image,
    pull_docker_image,
    validate_docker_installation,
)
from ..utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)


class KubernetesSubmittedRun(AbstractRun):
    from kubernetes.client.api.batch_v1_api import BatchV1Api
    from kubernetes.client.models.v1_job import V1Job

    def __init__(self, api: BatchV1Api, job: V1Job, name: str) -> None:
        self.api = api
        self.job = job
        self.name = name

    @property
    def id(self) -> str:
        return self.name

    def wait(self) -> bool:
        pass

    def get_status(self) -> Status:
        response = self.api.read_namespaced_job_status(name=self.name, namespace='default')
        status = response.status
        # todo: at the moment we only handle the single pod case
        if status.succeeded == 1:
            return Status("finished")
        elif status.failed == 1:
            return Status("failed")
        elif status.active == 1:
            return Status("running")
        return Status("unknown")

    def cancel(self) -> None:
        self.job.spec.suspend = True
        response = self.api.patch_namespaced_job(name=self.name, namespace='default', body=self.job)
        # @@@
        print('@@@@@@@@', response.status)


class KubernetesRunner(AbstractRunner):
    def run(self, launch_project: LaunchProject) -> Optional[AbstractRun]:
        resource_args = launch_project.resource_args.get("kubernetes")
        if resource_args is None:
            raise LaunchError("No Kubernetes resource args specified. Specify args via --resource-args with a JSON file or string under top-level key kubernetes")
        # allow users to specify template or entire spec
        job_spec_dict = resource_args.get("job_spec", {}) # @@@ accept yaml and files

        registry = resource_args.get("registry")

        # @@@ todo

        config.load_kube_config()

        # @@@ todo

        batch_api = client.BatchV1Api()

        # @@@ todo
        validate_docker_installation()
        entry_point = launch_project.get_single_entry_point()
        docker_args: Dict[str, Any] = self.backend_config[PROJECT_DOCKER_ARGS]
        if docker_args:
            wandb.termwarn(
                "Docker args are not supported for Kubernetes. Not using docker args"
            )
        if launch_project.docker_image:
            pull_docker_image(launch_project.docker_image)
            image_uri = launch_project.docker_image
        else:
            # todo: handle registry
            image_uri = construct_local_image_uri(launch_project)

            # @@@
            tmp = "us-east1-docker.pkg.dev/playground-111/launch-vertex-test/"
            image_uri = tmp + image_uri

            generate_docker_image(self._api, launch_project, image_uri, entry_point, docker_args, runner_type="kubernetes")

            repo, tag = image_uri.split(":")
            docker.push(repo, tag)

        import random   # @@@
        rand = str(random.random())[-4:]
        job_name = 'test-job-name' + rand

        container = client.V1Container(
            name='container-name', # @@@
            image=image_uri,
            args=[], # @@@ entrypoint vs args vs docker run ?
        )

        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={'name': job_name}),
            spec=client.V1PodSpec(containers=[container], restart_policy="Never"),
        )

        job = client.V1Job(
            api_version='batch/v1',
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name),
            spec=client.V1JobSpec(template=template),
        )

        # create & start job
        response = batch_api.create_namespaced_job(body=job, namespace="default")
        wandb.termlog("Job created with status {status}.".format(status=response.status))


        submitted_job = KubernetesSubmittedRun(batch_api, job, job_name)

        # @@@ clean up job? on some interval


        return submitted_job

