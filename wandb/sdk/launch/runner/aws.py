import configparser
import json
import logging
import os
import re
import signal
import subprocess
import time
from typing import Any, Dict, List, Optional

import base64
import boto3
import docker
import wandb
from wandb.errors import CommError, LaunchError

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import (
    DEFAULT_LAUNCH_METADATA_PATH,
    get_entry_point_command,
    LaunchProject,
)
from ..docker import (
    build_docker_image_for_aws,
    docker_image_exists,
    docker_image_inspect,
    generate_docker_base_image,
    get_docker_command_aws,
    pull_docker_image,
    validate_docker_installation,
)
from ..utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)


_logger = logging.getLogger(__name__)


class AWSSubmittedRun(AbstractRun):
    """Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point command locally."""

    def __init__(self, training_job_name, client) -> None:
        super().__init__()
        self.client = client
        self.training_job_name = training_job_name
        self._status = Status("starting")

    @property
    def id(self) -> int:
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
            self.client().stop_training_job(TrainingJobName=self.training_job_name)
            self.wait()

    def get_status(self) -> Status:
        job_status = self.client().describe_training_job(
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


class AWSRunner(AbstractRunner):
    """Runner class, uses a project to create a LocallySubmittedRun."""

    def run(self, launch_project: LaunchProject) -> Optional[AbstractRun]:
        validate_docker_installation()
        region = None
        if launch_project.aws.get("region") is not None:
            region = launch_project.aws["region"]
        elif launch_project.aws.get("config_path") is not None:
            config = configparser.ConfigParser()
            config.read(launch_project.aws.get("config_path"))
            region = config.get("default", "region")
        elif os.path.exists(os.path.expanduser("~/.aws/config")):
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
        username, password = (
            base64.b64decode(token["authorizationData"][0]["authorizationToken"])
            .decode()
            .split(":")
        )

        auth_config = {"username": username, "password": password}

        repository = launch_project.aws.get("repository") or "my-test-repository"
        aws_tag = (
            token["authorizationData"][0]["proxyEndpoint"].lstrip("https://")
            + f"/{repository}"
        )

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
        command_separator = " "

        container_inspect = docker_image_inspect(launch_project.base_image)
        container_workdir = container_inspect["ContainerConfig"].get("WorkingDir", "/")
        container_env: List[str] = container_inspect["ContainerConfig"]["Env"]

        env_vars = {
            "WANDB_BASE_URL": self._api.settings("base_url"),
            "WANDB_API_KEY": self._api.api_key,
            "WANDB_PROJECT": launch_project.target_project,
            "WANDB_ENTITY": launch_project.target_entity,
            "WANDB_LAUNCH": True,
            "WANDB_LAUNCH_CONFIG_PATH": os.path.join(
                container_workdir, DEFAULT_LAUNCH_METADATA_PATH
            ),
            "WANDB_RUN_ID": launch_project.run_id or None,
            "WANDB_DOCKER": launch_project.docker_image,
        }
        command_args = get_entry_point_command(
            entry_point, launch_project.override_args
        )

        command_args = [command_arg.split(" ") for command_arg in command_args][0]

        if launch_project.docker_image is None or launch_project.build_image:
            image = build_docker_image_for_aws(
                launch_project=launch_project,
                api=self._api,
                copy_code=copy_code,
                workdir=container_workdir,
                container_env=container_env,
                tag=aws_tag,
                env_vars=env_vars,
                command_args=command_args,
            )
        else:
            image = launch_project.docker_image
        docker_client = docker.from_env()
        login_resp = docker_client.login(
            username, password, registry=token["authorizationData"][0]["proxyEndpoint"]
        )
        if login_resp.get("Status") != "Login Succeeded":
            raise LaunchError("Unable to login to ECR")
        wandb.termlog(f"Pushing image {image} to ECR")
        push_resp = docker_client.images.push(
            aws_tag,
            auth_config=auth_config,
            tag="latest",
        )
        # TODO: handle push errors

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

        command_args += get_entry_point_command(
            entry_point, launch_project.override_args
        )

        command_str = command_separator.join(command_args)
        sanitized_command_str = re.sub(
            r"WANDB_API_KEY=\w+", "WANDB_API_KEY", command_str
        )
        with open(
            os.path.join(launch_project.aux_dir, DEFAULT_LAUNCH_METADATA_PATH), "w"
        ) as fp:
            json.dump(
                {
                    **launch_project.launch_spec,
                    "command": sanitized_command_str,
                    "dockerfile_contents": launch_project._dockerfile_contents,
                },
                fp,
            )
        wandb.termlog("Pushing container to ECR with tag: ")

        arn = launch_project.aws.get("RoleArn")
        if arn is None:
            arn = "arn:aws:iam::620830334183:role/KyleSagemaker"

        sagemaker_client = boto3.client("sagemaker", region_name=region)
        wandb.termlog(
            "Launching run on sagemaker with entrypoint: {}".format(
                " ".join(command_args)
            )
        )
        resp = sagemaker_client.create_training_job(
            AlgorithmSpecification={
                "TrainingImage": aws_tag,
                "TrainingInputMode": launch_project.aws.get("TrainingInputMode")
                or "File",
            },
            ResourceConfig=launch_project.aws.get("ResourceConfig")
            or {
                "InstanceCount": 1,
                "InstanceType": "ml.m4.xlarge",
                "VolumeSizeInGB": 2,
            },
            StoppingCondition={
                "MaxRuntimeInSeconds": launch_project.aws.get("MaxRuntimeInSeconds")
                or 3600
            },
            TrainingJobName=launch_project.run_id,
            RoleArn=arn,
            OutputDataConfig={
                "S3OutputPath": launch_project.aws.get("OutputDataConfig")
                or f"s3://wandb-output/{launch_project.run_id}/output"
            },
        )

        if resp.get("TrainingJobArn") is None:
            raise LaunchError("Unable to create training job")
        run = AWSSubmittedRun(launch_project.run_id, sagemaker_client)
        return run

        # run = _run_entry_point(command_str, launch_project.project_dir)
        # if synchronous:
        #     run.wait()
        # return run


def _run_sagemaker_command(command: str, image_tag: str):
    pass
