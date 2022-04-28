import configparser
import logging
import os
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

if False:
    import boto3  # type: ignore
import wandb
from wandb.apis.internal import Api
import wandb.docker as docker
from wandb.errors import LaunchError
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.util import get_module

from .abstract import AbstractRun, AbstractRunner, Status
from .._project_spec import (
    get_entry_point_command,
    LaunchProject,
)
from ..builder.build import (
    get_env_vars_dict,
)
from ..utils import PROJECT_DOCKER_ARGS, PROJECT_SYNCHRONOUS, run_shell, to_camel_case


_logger = logging.getLogger(__name__)


class SagemakerSubmittedRun(AbstractRun):
    """Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point command on aws sagemaker."""

    def __init__(self, training_job_name: str, client: "boto3.Client") -> None:
        super().__init__()
        self.client = client
        self.training_job_name = training_job_name
        self._status = Status("running")

    @property
    def id(self) -> str:
        return f"sagemaker-{self.training_job_name}"

    def wait(self) -> bool:
        while True:
            status_state = self.get_status().state
            wandb.termlog(
                f"Training job {self.training_job_name} status: {status_state}"
            )
            if status_state in ["stopped", "failed", "finished"]:
                break
            time.sleep(5)
        return status_state == "finished"

    def cancel(self) -> None:
        # Interrupt child process if it hasn't already exited
        status = self.get_status()
        if status.state == "running":
            self.client.stop_training_job(TrainingJobName=self.training_job_name)
            self.wait()

    def get_status(self) -> Status:
        job_status = self.client.describe_training_job(
            TrainingJobName=self.training_job_name
        )["TrainingJobStatus"]
        if job_status == "Completed" or job_status == "Stopped":
            self._status = Status("finished")
        elif job_status == "Failed":
            self._status = Status("failed")
        elif job_status == "Stopping":
            self._status = Status("stopping")
        elif job_status == "InProgress":
            self._status = Status("running")
        return self._status


class AWSSagemakerRunner(AbstractRunner):
    """Runner class, uses a project to create a SagemakerSubmittedRun."""

    def run(
        self,
        launch_project: LaunchProject,
        builder: AbstractBuilder,
        registry_config: Dict[str, Any],
    ) -> Optional[AbstractRun]:
        _logger.info("using AWSSagemakerRunner")

        boto3 = get_module(
            "boto3",
            "AWSSagemakerRunner requires boto3 to be installed,  install with pip install wandb[launch]",
        )

        given_sagemaker_args = launch_project.resource_args.get("sagemaker")
        if given_sagemaker_args is None:
            raise LaunchError(
                "No sagemaker args specified. Specify sagemaker args in resource_args"
            )
        if (
            given_sagemaker_args.get(
                "EcrRepoName", given_sagemaker_args.get("ecr_repo_name")
            )
            is None
        ):
            raise LaunchError(
                "AWS sagemaker requires an ECR Repo to push the container to "
                "set this by adding a `EcrRepoName` key to the sagemaker"
                "field of resource_args"
            )

        region = get_region(given_sagemaker_args)
        access_key, secret_key = get_aws_credentials(given_sagemaker_args)
        client = boto3.client(
            "sts", aws_access_key_id=access_key, aws_secret_access_key=secret_key
        )
        account_id = client.get_caller_identity()["Account"]

        # if the user provided the image they want to use, use that, but warn it won't have swappable artifacts
        if (
            given_sagemaker_args.get("AlgorithmSpecification", {}).get("TrainingImage")
            is not None
        ):
            sagemaker_client = boto3.client(
                "sagemaker",
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            sagemaker_args = build_sagemaker_args(launch_project, self._api, account_id)
            _logger.info(
                f"Launching sagemaker job on user supplied image with args: {sagemaker_args}"
            )
            run = launch_sagemaker_job(launch_project, sagemaker_args, sagemaker_client)
            if self.backend_config[PROJECT_SYNCHRONOUS]:
                run.wait()
            return run

        _logger.info("Connecting to AWS ECR Client")
        ecr_client = boto3.client(
            "ecr",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        token = ecr_client.get_authorization_token()

        ecr_repo_name = given_sagemaker_args.get(
            "EcrRepoName", given_sagemaker_args.get("ecr_repo_name")
        )
        if ecr_repo_name:
            repository = (
                token["authorizationData"][0]["proxyEndpoint"].replace("https://", "")
                + f"/{ecr_repo_name}"
            )
        else:
            repository = registry_config.get("url")

        if repository is None:
            raise LaunchError(
                "Must provide a repository url either through resource args or launch config file"
            )

        if registry_config.get("ecr-repo-provider", "aws") != "aws":
            raise LaunchError(
                "Sagemaker jobs requires an AWS ECR Repo to push the container to"
            )
        # TODO: handle login credentials gracefully
        login_credentials = registry_config.get("credentials")
        if login_credentials is not None:
            wandb.termwarn(
                "Ignoring registry credentials for ECR, using those found on the system"
            )

        if builder.type != "kaniko":
            _logger.info("Logging in to AWS ECR")
            login_resp = aws_ecr_login(region, repository)
            if login_resp is None or "Login Succeeded" not in login_resp:
                raise LaunchError(f"Unable to login to ECR, response: {login_resp}")

        docker_args = self.backend_config[PROJECT_DOCKER_ARGS]
        if docker_args and list(docker_args) != ["docker_image"]:
            wandb.termwarn(
                "Docker args are not supported for Sagemaker Resource. Not using docker args"
            )

        entry_point = launch_project.get_single_entry_point()

        if launch_project.docker_image:
            image = launch_project.docker_image
        else:
            # build our own image
            image = builder.build_image(
                launch_project,
                repository,
                entry_point,
                {},
            )

        if not self.ack_run_queue_item(launch_project):
            return None

        _logger.info("Connecting to sagemaker client")

        sagemaker_client = boto3.client(
            "sagemaker",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

        command_args = get_entry_point_command(
            entry_point, launch_project.override_args
        )
        if command_args:
            wandb.termlog(f"Launching run on sagemaker with entrypoint: {command_args}")
        else:
            wandb.termlog(
                "Launching run on sagemaker with user-provided entrypoint in image"
            )

        sagemaker_args = build_sagemaker_args(
            launch_project, self._api, account_id, image
        )
        _logger.info(f"Launching sagemaker job with args: {sagemaker_args}")
        run = launch_sagemaker_job(launch_project, sagemaker_args, sagemaker_client)
        if self.backend_config[PROJECT_SYNCHRONOUS]:
            run.wait()
        return run


def aws_ecr_login(region: str, registry: str) -> Optional[str]:
    pw_command = ["aws", "ecr", "get-login-password", "--region", region]
    try:
        pw = run_shell(pw_command)[0]
    except subprocess.CalledProcessError:
        raise LaunchError(
            "Unable to get login password. Please ensure you have AWS credentials configured"
        )
    try:
        docker_login_process = docker.login("AWS", pw, registry)
    except Exception:
        raise LaunchError(f"Failed to login to ECR {registry}")
    return docker_login_process


def merge_aws_tag_with_algorithm_specification(
    algorithm_specification: Optional[Dict[str, Any]], aws_tag: Optional[str]
) -> Dict[str, Any]:
    """
    AWS Sagemaker algorithms require a training image and an input mode.
    If the user does not specify the specification themselves, define the spec
    minimally using these two fields. Otherwise, if they specify the AlgorithmSpecification
    set the training image if it is not set.
    """
    if algorithm_specification is None:
        return {
            "TrainingImage": aws_tag,
            "TrainingInputMode": "File",
        }
    elif algorithm_specification.get("TrainingImage") is None:
        algorithm_specification["TrainingImage"] = aws_tag
    if algorithm_specification["TrainingImage"] is None:
        raise LaunchError("Failed determine tag for training image")
    return algorithm_specification


def build_sagemaker_args(
    launch_project: LaunchProject,
    api: Api,
    account_id: str,
    aws_tag: Optional[str] = None,
) -> Dict[str, Any]:
    sagemaker_args = {}
    given_sagemaker_args = launch_project.resource_args.get("sagemaker")
    if given_sagemaker_args is None:
        raise LaunchError(
            "No sagemaker args specified. Specify sagemaker args in resource_args"
        )
    sagemaker_args["TrainingJobName"] = (
        given_sagemaker_args.get("TrainingJobName") or launch_project.run_id
    )

    sagemaker_args[
        "AlgorithmSpecification"
    ] = merge_aws_tag_with_algorithm_specification(
        given_sagemaker_args.get(
            "AlgorithmSpecification",
            given_sagemaker_args.get("algorithm_specification"),
        ),
        aws_tag,
    )

    sagemaker_args["RoleArn"] = get_role_arn(given_sagemaker_args, account_id)

    camel_case_args = {
        to_camel_case(key): item for key, item in given_sagemaker_args.items()
    }
    sagemaker_args = {
        **camel_case_args,
        **sagemaker_args,
    }

    if sagemaker_args.get("OutputDataConfig") is None:
        raise LaunchError(
            "Sagemaker launcher requires an OutputDataConfig Sagemaker resource argument"
        )

    if sagemaker_args.get("ResourceConfig") is None:
        raise LaunchError(
            "Sagemaker launcher requires a ResourceConfig Sagemaker resource argument"
        )

    if sagemaker_args.get("StoppingCondition") is None:
        raise LaunchError(
            "Sagemaker launcher requires a StoppingCondition Sagemaker resource argument"
        )

    given_env = given_sagemaker_args.get(
        "Environment", sagemaker_args.get("environment", {})
    )
    calced_env = get_env_vars_dict(launch_project, api)
    total_env = {**calced_env, **given_env}
    sagemaker_args["Environment"] = total_env

    # remove args that were passed in for launch but not passed to sagemaker
    sagemaker_args.pop("EcrRepoName", None)
    sagemaker_args.pop("region", None)
    sagemaker_args.pop("profile", None)

    # clear the args that are None so they are not passed
    filtered_args = {k: v for k, v in sagemaker_args.items() if v is not None}

    return filtered_args


def launch_sagemaker_job(
    launch_project: LaunchProject,
    sagemaker_args: Dict[str, Any],
    sagemaker_client: "boto3.Client",
) -> SagemakerSubmittedRun:
    training_job_name = sagemaker_args.get("TrainingJobName") or launch_project.run_id
    resp = sagemaker_client.create_training_job(**sagemaker_args)

    if resp.get("TrainingJobArn") is None:
        raise LaunchError("Unable to create training job")

    run = SagemakerSubmittedRun(training_job_name, sagemaker_client)
    wandb.termlog("Run job submitted with arn: {}".format(resp.get("TrainingJobArn")))
    url = "https://{region}.console.aws.amazon.com/sagemaker/home?region={region}#/jobs/{job_name}".format(
        region=sagemaker_client.meta.region_name, job_name=training_job_name
    )
    wandb.termlog(f"See training job status at: {url}")
    return run


def get_region(sagemaker_args: Dict[str, Any]) -> str:
    region = sagemaker_args.get("region")
    if region is None:
        region = os.environ.get("AWS_DEFAULT_REGION")
    if region is None and os.path.exists(os.path.expanduser("~/.aws/config")):
        config = configparser.ConfigParser()
        config.read(os.path.expanduser("~/.aws/config"))
        section = sagemaker_args.get("profile") or "default"
        try:
            region = config.get(section, "region")
        except (configparser.NoOptionError, configparser.NoSectionError):
            raise LaunchError(
                "Unable to detemine default region from ~/.aws/config. "
                "Please specify region in resource args or specify config "
                "section as 'profile'"
            )

    if region is None:
        raise LaunchError(
            "AWS region not specified and ~/.aws/config not found. Configure AWS"
        )
    assert isinstance(region, str)
    return region


def get_aws_credentials(sagemaker_args: Dict[str, Any]) -> Tuple[str, str]:
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if (
        access_key is None
        or secret_key is None
        and os.path.exists(os.path.expanduser("~/.aws/credentials"))
    ):
        profile = sagemaker_args.get("profile") or "default"
        config = configparser.ConfigParser()
        config.read(os.path.expanduser("~/.aws/credentials"))
        try:
            access_key = config.get(profile, "aws_access_key_id")
            secret_key = config.get(profile, "aws_secret_access_key")
        except (configparser.NoOptionError, configparser.NoSectionError):
            raise LaunchError(
                "Unable to get aws credentials from ~/.aws/credentials. "
                "Please set aws credentials in environments variables, or "
                "check your credentials in ~/.aws/credentials. Use resource "
                "args to specify the profile using 'profile'"
            )

    if access_key is None or secret_key is None:
        raise LaunchError("AWS credentials not found")
    return access_key, secret_key


def get_role_arn(sagemaker_args: Dict[str, Any], account_id: str) -> str:
    role_arn = sagemaker_args.get("RoleArn") or sagemaker_args.get("role_arn")
    if role_arn is None or not isinstance(role_arn, str):
        raise LaunchError(
            "AWS sagemaker require a string RoleArn set this by adding a `RoleArn` key to the sagemaker"
            "field of resource_args"
        )
    if role_arn.startswith("arn:aws:iam::"):
        return role_arn

    return f"arn:aws:iam::{account_id}:role/{role_arn}"
