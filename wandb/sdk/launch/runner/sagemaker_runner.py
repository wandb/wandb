"""Implementation of the SageMakerRunner class."""

import asyncio
import logging
from typing import Any, Dict, List, Optional, cast

if False:
    import boto3  # type: ignore

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch.environment.aws_environment import AwsEnvironment
from wandb.sdk.launch.errors import LaunchError

from .._project_spec import EntryPoint, LaunchProject
from ..registry.abstract import AbstractRegistry
from ..utils import (
    LOG_PREFIX,
    MAX_ENV_LENGTHS,
    PROJECT_SYNCHRONOUS,
    event_loop_thread_exec,
    to_camel_case,
)
from .abstract import AbstractRun, AbstractRunner, Status

_logger = logging.getLogger(__name__)


class SagemakerSubmittedRun(AbstractRun):
    """Instance of ``AbstractRun`` corresponding to a subprocess launched to run an entry point command on aws sagemaker."""

    def __init__(
        self,
        training_job_name: str,
        client: "boto3.Client",
        log_client: Optional["boto3.Client"] = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.log_client = log_client
        self.training_job_name = training_job_name
        self._status = Status("running")

    @property
    def id(self) -> str:
        return f"sagemaker-{self.training_job_name}"

    async def get_logs(self) -> Optional[str]:
        if self.log_client is None:
            return None
        try:
            describe_log_streams = event_loop_thread_exec(
                self.log_client.describe_log_streams
            )
            describe_res = await describe_log_streams(
                logGroupName="/aws/sagemaker/TrainingJobs",
                logStreamNamePrefix=self.training_job_name,
            )
            if len(describe_res["logStreams"]) == 0:
                wandb.termwarn(
                    f"Failed to get logs for training job: {self.training_job_name}"
                )
                return None
            log_name = describe_res["logStreams"][0]["logStreamName"]
            get_log_events = event_loop_thread_exec(self.log_client.get_log_events)
            res = await get_log_events(
                logGroupName="/aws/sagemaker/TrainingJobs",
                logStreamName=log_name,
            )
            assert "events" in res
            return "\n".join(
                [f'{event["timestamp"]}:{event["message"]}' for event in res["events"]]
            )
        except self.log_client.exceptions.ResourceNotFoundException:
            wandb.termwarn(
                f"Failed to get logs for training job: {self.training_job_name}"
            )
            return None
        except Exception as e:
            wandb.termwarn(
                f"Failed to handle logs for training job: {self.training_job_name} with error {str(e)}"
            )
            return None

    async def wait(self) -> bool:
        while True:
            status_state = (await self.get_status()).state
            wandb.termlog(
                f"{LOG_PREFIX}Training job {self.training_job_name} status: {status_state}"
            )
            if status_state in ["stopped", "failed", "finished"]:
                break
            await asyncio.sleep(5)
        return status_state == "finished"

    async def cancel(self) -> None:
        # Interrupt child process if it hasn't already exited
        status = await self.get_status()
        if status.state == "running":
            self.client.stop_training_job(TrainingJobName=self.training_job_name)
            await self.wait()

    async def get_status(self) -> Status:
        describe_training_job = event_loop_thread_exec(
            self.client.describe_training_job
        )
        job_status = (
            await describe_training_job(TrainingJobName=self.training_job_name)
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


class SageMakerRunner(AbstractRunner):
    """Runner class, uses a project to create a SagemakerSubmittedRun."""

    def __init__(
        self,
        api: Api,
        backend_config: Dict[str, Any],
        environment: AwsEnvironment,
        registry: AbstractRegistry,
    ) -> None:
        """Initialize the SagemakerRunner.

        Arguments:
            api (Api): The API instance.
            backend_config (Dict[str, Any]): The backend configuration.
            environment (AwsEnvironment): The AWS environment.

        Raises:
            LaunchError: If the runner cannot be initialized.
        """
        super().__init__(api, backend_config)
        self.environment = environment
        self.registry = registry

    async def run(
        self,
        launch_project: LaunchProject,
        image_uri: str,
    ) -> Optional[AbstractRun]:
        """Run a project on Amazon Sagemaker.

        Arguments:
            launch_project (LaunchProject): The project to run.

        Returns:
            Optional[AbstractRun]: The run instance.

        Raises:
            LaunchError: If the launch is unsuccessful.
        """
        _logger.info("using AWSSagemakerRunner")

        given_sagemaker_args = launch_project.resource_args.get("sagemaker")
        if given_sagemaker_args is None:
            raise LaunchError(
                "No sagemaker args specified. Specify sagemaker args in resource_args"
            )

        default_output_path = self.backend_config.get("runner", {}).get(
            "s3_output_path"
        )
        if default_output_path is not None and not default_output_path.startswith(
            "s3://"
        ):
            default_output_path = f"s3://{default_output_path}"

        session = await self.environment.get_session()
        client = await event_loop_thread_exec(session.client)("sts")
        caller_id = client.get_caller_identity()
        account_id = caller_id["Account"]
        _logger.info(f"Using account ID {account_id}")
        partition = await self.environment.get_partition()
        role_arn = get_role_arn(
            given_sagemaker_args, self.backend_config, account_id, partition
        )

        # Create a sagemaker client to launch the job.
        sagemaker_client = session.client("sagemaker")
        log_client = None
        try:
            log_client = session.client("logs")
        except Exception as e:
            wandb.termwarn(
                f"Failed to connect to cloudwatch logs with error {str(e)}, logs will not be available"
            )

        # if the user provided the image they want to use, use that, but warn it won't have swappable artifacts
        if (
            given_sagemaker_args.get("AlgorithmSpecification", {}).get("TrainingImage")
            is not None
        ):
            sagemaker_args = build_sagemaker_args(
                launch_project,
                self._api,
                role_arn,
                launch_project.override_entrypoint,
                launch_project.override_args,
                MAX_ENV_LENGTHS[self.__class__.__name__],
                given_sagemaker_args.get("AlgorithmSpecification", {}).get(
                    "TrainingImage"
                ),
                default_output_path,
            )
            _logger.info(
                f"Launching sagemaker job on user supplied image with args: {sagemaker_args}"
            )
            run = await launch_sagemaker_job(
                launch_project, sagemaker_args, sagemaker_client, log_client
            )
            if self.backend_config[PROJECT_SYNCHRONOUS]:
                await run.wait()
            return run

        _logger.info("Connecting to sagemaker client")
        entry_point = (
            launch_project.override_entrypoint or launch_project.get_job_entry_point()
        )
        command_args = []
        if entry_point is not None:
            command_args += entry_point.command
        command_args += launch_project.override_args
        if command_args:
            command_str = " ".join(command_args)
            wandb.termlog(
                f"{LOG_PREFIX}Launching run on sagemaker with entrypoint: {command_str}"
            )
        else:
            wandb.termlog(
                f"{LOG_PREFIX}Launching run on sagemaker with user-provided entrypoint in image"
            )
        sagemaker_args = build_sagemaker_args(
            launch_project,
            self._api,
            role_arn,
            entry_point,
            launch_project.override_args,
            MAX_ENV_LENGTHS[self.__class__.__name__],
            image_uri,
            default_output_path,
        )
        _logger.info(f"Launching sagemaker job with args: {sagemaker_args}")
        run = await launch_sagemaker_job(
            launch_project, sagemaker_args, sagemaker_client, log_client
        )
        if self.backend_config[PROJECT_SYNCHRONOUS]:
            await run.wait()
        return run


def merge_image_uri_with_algorithm_specification(
    algorithm_specification: Optional[Dict[str, Any]],
    image_uri: Optional[str],
    entrypoint_command: List[str],
    args: Optional[List[str]],
) -> Dict[str, Any]:
    """Create an AWS AlgorithmSpecification.

    AWS Sagemaker algorithms require a training image and an input mode. If the user
    does not specify the specification themselves, define the spec minimally using these
    two fields. Otherwise, if they specify the AlgorithmSpecification set the training
    image if it is not set.
    """
    if algorithm_specification is None:
        algorithm_specification = {
            "TrainingImage": image_uri,
            "TrainingInputMode": "File",
        }
    else:
        if image_uri:
            algorithm_specification["TrainingImage"] = image_uri
    if entrypoint_command:
        algorithm_specification["ContainerEntrypoint"] = entrypoint_command
    if args:
        algorithm_specification["ContainerArguments"] = args

    if algorithm_specification["TrainingImage"] is None:
        raise LaunchError("Failed determine tag for training image")
    return algorithm_specification


def build_sagemaker_args(
    launch_project: LaunchProject,
    api: Api,
    role_arn: str,
    entry_point: Optional[EntryPoint],
    args: Optional[List[str]],
    max_env_length: int,
    image_uri: str,
    default_output_path: Optional[str] = None,
) -> Dict[str, Any]:
    sagemaker_args: Dict[str, Any] = {}
    resource_args = launch_project.fill_macros(image_uri)
    given_sagemaker_args: Optional[Dict[str, Any]] = resource_args.get("sagemaker")

    if given_sagemaker_args is None:
        raise LaunchError(
            "No sagemaker args specified. Specify sagemaker args in resource_args"
        )
    if (
        given_sagemaker_args.get("OutputDataConfig") is None
        and default_output_path is not None
    ):
        sagemaker_args["OutputDataConfig"] = {"S3OutputPath": default_output_path}
    else:
        sagemaker_args["OutputDataConfig"] = given_sagemaker_args.get(
            "OutputDataConfig"
        )

    if sagemaker_args.get("OutputDataConfig") is None:
        raise LaunchError(
            "Sagemaker launcher requires an OutputDataConfig Sagemaker resource argument"
        )
    training_job_name = cast(
        str, (given_sagemaker_args.get("TrainingJobName") or launch_project.run_id)
    )
    sagemaker_args["TrainingJobName"] = training_job_name
    entry_cmd = entry_point.command if entry_point else []

    sagemaker_args["AlgorithmSpecification"] = (
        merge_image_uri_with_algorithm_specification(
            given_sagemaker_args.get(
                "AlgorithmSpecification",
                given_sagemaker_args.get("algorithm_specification"),
            ),
            image_uri,
            entry_cmd,
            args,
        )
    )

    sagemaker_args["RoleArn"] = role_arn

    camel_case_args = {
        to_camel_case(key): item for key, item in given_sagemaker_args.items()
    }
    sagemaker_args = {
        **camel_case_args,
        **sagemaker_args,
    }

    if sagemaker_args.get("ResourceConfig") is None:
        raise LaunchError(
            "Sagemaker launcher requires a ResourceConfig resource argument"
        )

    if sagemaker_args.get("StoppingCondition") is None:
        raise LaunchError(
            "Sagemaker launcher requires a StoppingCondition resource argument"
        )

    given_env = given_sagemaker_args.get(
        "Environment", sagemaker_args.get("environment", {})
    )
    calced_env = launch_project.get_env_vars_dict(api, max_env_length)
    total_env = {**calced_env, **given_env}
    sagemaker_args["Environment"] = total_env

    # Add wandb tag
    tags = sagemaker_args.get("Tags", [])
    tags.append({"Key": "WandbRunId", "Value": launch_project.run_id})
    sagemaker_args["Tags"] = tags

    # remove args that were passed in for launch but not passed to sagemaker
    sagemaker_args.pop("EcrRepoName", None)
    sagemaker_args.pop("region", None)
    sagemaker_args.pop("profile", None)

    # clear the args that are None so they are not passed
    filtered_args = {k: v for k, v in sagemaker_args.items() if v is not None}

    return filtered_args


async def launch_sagemaker_job(
    launch_project: LaunchProject,
    sagemaker_args: Dict[str, Any],
    sagemaker_client: "boto3.Client",
    log_client: Optional["boto3.Client"] = None,
) -> SagemakerSubmittedRun:
    training_job_name = sagemaker_args.get("TrainingJobName") or launch_project.run_id
    create_training_job = event_loop_thread_exec(sagemaker_client.create_training_job)
    resp = await create_training_job(**sagemaker_args)

    if resp.get("TrainingJobArn") is None:
        raise LaunchError("Failed to create training job when submitting to SageMaker")

    run = SagemakerSubmittedRun(training_job_name, sagemaker_client, log_client)
    wandb.termlog(
        f"{LOG_PREFIX}Run job submitted with arn: {resp.get('TrainingJobArn')}"
    )
    url = "https://{region}.console.aws.amazon.com/sagemaker/home?region={region}#/jobs/{job_name}".format(
        region=sagemaker_client.meta.region_name, job_name=training_job_name
    )
    wandb.termlog(f"{LOG_PREFIX}See training job status at: {url}")
    return run


def get_role_arn(
    sagemaker_args: Dict[str, Any],
    backend_config: Dict[str, Any],
    account_id: str,
    partition: str,
) -> str:
    """Get the role arn from the sagemaker args or the backend config."""
    role_arn = sagemaker_args.get("RoleArn") or sagemaker_args.get("role_arn")
    if role_arn is None:
        role_arn = backend_config.get("runner", {}).get("role_arn")
    if role_arn is None or not isinstance(role_arn, str):
        raise LaunchError(
            "AWS sagemaker require a string RoleArn set this by adding a `RoleArn` key to the sagemaker"
            "field of resource_args"
        )
    if role_arn.startswith(f"arn:{partition}:iam::"):
        return role_arn  # type: ignore

    return f"arn:{partition}:iam::{account_id}:role/{role_arn}"
