import configparser
import itertools
import json
import logging
import os
import subprocess
import time
from typing import List, Optional

import wandb
import wandb.docker as docker
from wandb.errors import CommError, LaunchError
from wandb.util import get_module

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import (
    DEFAULT_LAUNCH_METADATA_PATH,
    LaunchProject,
    get_entry_point_command,
)
from ..docker import (
    build_docker_image_if_needed,
    construct_local_image_uri,
    docker_image_exists,
    docker_image_inspect,
    generate_docker_base_image,
    get_full_command,
    pull_docker_image,
    validate_docker_installation,
)
from ..utils import PROJECT_DOCKER_ARGS


_logger = logging.getLogger(__name__)


class AWSSubmittedRun(AbstractRun):
    """Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point command locally."""

    def __init__(self, training_job_name: str, client: "boto3.Client") -> None:
        super().__init__()
        self.client = client
        self.training_job_name = training_job_name
        self._status = Status("starting")

    @property
    def id(self) -> str:
        return f"sagemaker-{self.training_job_name}"

    def wait(self) -> bool:
        while True:
            status_state = self.get_status().state
            if status_state not in ["running", "starting", "unknown"]:
                break
            time.sleep(5)
        return status_state == "finished"

    def cancel(self) -> None:
        # Interrupt child process if it hasn't already exited
        status = self.get_status()
        if status.state in ["running", "starting", "unknown"]:
            self.client.stop_training_job(TrainingJobName=self.training_job_name)
            self.wait()

    def get_status(self) -> Status:
        job_status = self.client.describe_training_job(
            TrainingJobName=self.training_job_name
        )["TrainingJobStatus"]
        if job_status == "Completed":
            self._status = Status("finished")
        elif job_status == "Failed":
            self._status = Status("failed")
        elif job_status == "Stopping":
            self._status = Status("stopping")
        elif job_status == "Stopped":
            self._status = Status("finished")
        elif job_status == "InProgress":
            self._status = Status("running")
        return self._status


class AWSSagemakerRunner(AbstractRunner):
    """Runner class, uses a project to create a AWSSubmittedRun."""

    def run(self, launch_project: LaunchProject) -> Optional[AbstractRun]:
        boto3 = get_module("boto3", "AWSSagemakerRunner requires boto3 to be installed")
        validate_docker_installation()
        assert (
            launch_project.resource_args.get("ecr_name") is not None
        ), "AWS jobs require an ecr repository name, set this using `--resource_args ecr_name=<repo_name>`"
        assert (
            launch_project.resource_args.get("role_arn") is not None
        ), "AWS jobs require a role ARN, set this using `resource_args role_arn=<role_arn>` "

        region = None
        if os.path.exists(os.path.expanduser("~/.aws/config")):
            config = configparser.ConfigParser()
            config.read(os.path.expanduser("~/.aws/config"))
            region = config.get("default", "region")
        assert region is not None, "AWS region not specified."

        access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if (
            access_key is None
            or secret_key is None
            and os.path.exists(os.path.expanduser("~/.aws/credentials"))
        ):
            config = configparser.ConfigParser()
            config.read(os.path.expanduser("~/.aws/credentials"))
            access_key = config.get("default", "aws_access_key_id")
            secret_key = config.get("default", "aws_secret_access_key")
        if access_key is None or secret_key is None:
            raise LaunchError("AWS credentials not found.")

        ecr_client = boto3.client(
            "ecr",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        token = ecr_client.get_authorization_token()

        ecr_name = launch_project.resource_args.get("ecr_name")
        aws_registry = (
            token["authorizationData"][0]["proxyEndpoint"].lstrip("https://")
            + f"/{ecr_name}"
        )

        if self.backend_config[PROJECT_DOCKER_ARGS]:
            wandb.termwarn(
                "Docker args are not supported for AWS. Not using docker args."
            )

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

        command_separator = " "
        command_args = []

        container_inspect = docker_image_inspect(launch_project.base_image)
        container_workdir = container_inspect["ContainerConfig"].get("WorkingDir", "/")
        container_env: List[str] = container_inspect["ContainerConfig"]["Env"]

        if launch_project.docker_image is None or launch_project.build_image:
            image_uri = construct_local_image_uri(launch_project)
            command_args += get_entry_point_command(
                entry_point, launch_project.override_args
            )
            # create a flattened list of all the command inputs for the dockerfile
            command_args = list(
                itertools.chain(*[ca.split(" ") for ca in command_args])
            )
            sanitized_command_str = command_separator.join(command_args)
            with open(
                os.path.join(launch_project.project_dir, DEFAULT_LAUNCH_METADATA_PATH),
                "w",
            ) as f:
                json.dump(
                    {
                        **launch_project.launch_spec,
                        "command": sanitized_command_str,
                        "dockerfile_contents": launch_project._dockerfile_contents,
                    },
                    f,
                )
            image = build_docker_image_if_needed(
                launch_project=launch_project,
                api=self._api,
                copy_code=copy_code,
                workdir=container_workdir,
                container_env=container_env,
                runner_type="aws",
                image_uri=image_uri,
                command_args=command_args,
            )
        else:
            # TODO: rewrite env vars and copy code in supplied docker image
            wandb.termwarn(
                "Using supplied docker image: {}. Artifact swapping and launch metadata disabled".format(
                    launch_project.docker_image
                )
            )
            image_uri = launch_project.docker_image

        login_resp = aws_ecr_login(region, aws_registry)
        if "Login Succeeded" not in login_resp:
            raise LaunchError(f"Unable to login to ECR, response: {login_resp}")

        aws_tag = f"{aws_registry}:{launch_project.run_id}"
        docker.tag(image, aws_tag)
        push_resp = docker.push(aws_registry, launch_project.run_id)
        if push_resp is None:
            raise LaunchError("Failed to push image to repository.")
        if f"The push refers to repository [{aws_registry}]" not in push_resp:
            raise LaunchError(f"Unable to push image to ECR, response: {push_resp}")

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

        sagemaker_client = boto3.client("sagemaker", region_name=region)
        wandb.termlog(
            "Launching run on sagemaker with entrypoint: {}".format(
                " ".join(command_args)
            )
        )
        training_job_name = (
            launch_project.resource_args.get("TrainingJobName") or launch_project.run_id
        )
        resp = sagemaker_client.create_training_job(
            AlgorithmSpecification={
                "TrainingImage": aws_tag,
                "TrainingInputMode": launch_project.resource_args.get(
                    "TrainingInputMode"
                )
                or "File",
            },
            ResourceConfig=launch_project.resource_args.get("ResourceConfig")
            or {
                "InstanceCount": 1,
                "InstanceType": "ml.m4.xlarge",
                "VolumeSizeInGB": 2,
            },
            StoppingCondition=launch_project.resource_args.get("StoppingCondition")
            or {
                "MaxRuntimeInSeconds": launch_project.resource_args.get(
                    "MaxRuntimeInSeconds"
                )
                or 3600
            },
            TrainingJobName=training_job_name,
            RoleArn=launch_project.resource_args.get("role_arn"),
            OutputDataConfig={
                "S3OutputPath": launch_project.resource_args.get("OutputDataConfig")
                or f"s3://wandb-output/{launch_project.run_id}/output"
            },
        )

        if resp.get("TrainingJobArn") is None:
            raise LaunchError("Unable to create training job")

        run = AWSSubmittedRun(training_job_name, sagemaker_client)
        print("Run job submitted with arn: {}".format(resp.get("TrainingJobArn")))
        return run


def aws_ecr_login(region: str, registry: str) -> str:
    pw = subprocess.run(
        f"aws ecr get-login-password --region {region}".split(" "),
        capture_output=True,
        check=True,
    )
    login_process = subprocess.run(
        f"docker login --username AWS --password-stdin {registry}".split(" "),
        input=pw.stdout,
        capture_output=True,
        check=True,
    )
    return login_process.stdout.decode("utf-8")
