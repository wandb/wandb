"""
Implementation of launch agent.
"""

import json
import logging
import os
import random
import time
from typing import Any, Dict, List, TypeVar, Union

import wandb
from wandb.apis.internal import Api
from wandb.sdk.launch.runner.local import LocalSubmittedRun
import wandb.util as util
from wandb_gql import gql

from .._project_spec import create_project_from_spec, fetch_and_validate_project
from ..builder.loader import load_builder
from ..runner.abstract import AbstractRun
from ..runner.loader import load_backend
from ..utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
    resolve_build_and_registry_config,
)

AGENT_POLLING_INTERVAL = 10

AGENT_POLLING = "POLLING"
AGENT_RUNNING = "RUNNING"
AGENT_KILLED = "KILLED"
VALID_RESOURCES = ["cpus", "gpus", "ram"]
VALID_RUNNER_TYPES = ["kubernetes", "sagemaker", "local-process", "local-container"]

_logger = logging.getLogger(__name__)

RunQueue = TypeVar("RunQueue")


def kubernetes(agent, queue):
    valid = False
    return valid


def sagemaker(agent, queue):
    valid = False
    return valid


def local_process(agent, queue):
    agent_config = agent._configured_runners["local-process"]
    queue_config = queue["config"]["local-process"]

    label_satisfied = False
    for lbl in agent_config.get("labels", []):
        if lbl in queue_config.get("labels", []):
            label_satisfied = True

    resource_satisfied = True
    for criterion, requirement in queue_config.get("resources", {}).items():
        agent_config_resources = agent_config.get("resources", {})
        if (
            agent_config_resources
            and agent_config_resources.get(criterion) is not None
            and agent_config_resources.get(criterion) < requirement
        ):
            resource_satisfied = False

    return label_satisfied and resource_satisfied


def local_container(agent, queue):
    agent_config = agent._configured_runners["local-container"]
    queue_config = queue["config"]["local-container"]

    label_satisfied = False
    for lbl in agent_config.get("labels", []):
        if lbl in queue_config.get("labels", []):
            label_satisfied = True

    resource_satisfied = True
    for criterion, requirement in agent_config.get("resources", {}).items():
        queue_config_resources = queue_config.get("resources", {})
        if (
            queue_config_resources
            and queue_config_resources.get(criterion) is not None
            and queue_config_resources.get(criterion) < requirement
        ):
            resource_satisfied = False

    return label_satisfied and resource_satisfied


runner_dispatch = {
    "kubernetes": kubernetes,
    "sagemaker": sagemaker,
    "local-process": local_process,
    "local-container": local_container,
}


def merge_dicts(x, y):
    """
    https://stackoverflow.com/questions/47564712/merge-nested-dictionaries-by-appending

    Inserts items from dict x into dict y, prioritizing x if keys exist in both dicts
    """
    for key in y:
        if key in x:
            if isinstance(x[key], dict) and isinstance(y[key], dict):
                merge_dicts(x[key], y[key])
        else:
            x[key] = y[key]
    return x


def _convert_access(access: str) -> str:
    """Converts access string to a value accepted by wandb."""
    access = access.upper()
    assert (
        access == "PROJECT" or access == "USER"
    ), "Queue access must be either project or user"
    return access


class LaunchAgent:
    """Launch agent class which polls run given run queues and launches runs for wandb launch."""

    def __init__(self, api: Api, config: Dict[str, Any]):
        self._entity = config.get("entity")
        self._project = config.get("project")
        self._api = api
        self._base_url = self._api.settings().get("base_url")
        self._jobs: Dict[Union[int, str], AbstractRun] = {}
        self._ticks = 0
        self._running = 0
        self._cwd = os.getcwd()
        self._namespace = wandb.util.generate_id()
        self._access = _convert_access("project")
        self._configured_runners = self._configure_runners(config)
        if config.get("max_jobs") == -1:
            self._max_jobs = float("inf")
        else:
            self._max_jobs = config.get("max_jobs") or 1
        self.default_config: Dict[str, Any] = config

        # serverside creation
        self.gorilla_supports_agents = (
            self._api.launch_agent_introspection() is not None
        )
        self._queues = self._get_valid_run_queues()
        create_response = self._api.create_new_launch_agent(
            self._entity, self.gorilla_supports_agents, config=self._configured_runners
        )
        self._id = create_response["newLaunchAgentId"]
        self._name = ""  # hacky: want to display this to the user but we don't get it back from gql until polling starts. fix later

    @property
    def job_ids(self) -> List[Union[int, str]]:
        """Returns a list of keys running job ids for the agent."""
        return list(self._jobs.keys())

    def pop_from_queue(self, queue: RunQueue) -> Any:
        """Pops an item off the runqueue to run as a job."""
        try:
            rqi = self._api.pop_from_run_queue(
                queue["name"],
                entity=self._entity,
                project=queue["projectName"],
                agent_id=self._id,
            )
        except Exception as e:
            print("Exception:", e)
            return None
        return rqi

    def print_status(self) -> None:
        """Prints the current status of the agent."""
        project_queues = [f"{q['projectName']}/{q['name']}" for q in self._queues]
        wandb.termlog(f"LAUNCH AGENT POLLING {self._entity} on queues {project_queues}")

    def update_status(self, status: str) -> None:
        update_ret = self._api.update_new_launch_agent_status(
            self._id, status, self.gorilla_supports_agents
        )
        if not update_ret["success"]:
            wandb.termerror(f"Failed to update agent status to {status}")

    def finish_job_id(self, job_id: Union[str, int]) -> None:
        """Removes the job from our list for now."""
        # TODO:  keep logs or something for the finished jobs
        del self._jobs[job_id]
        self._running -= 1
        # update status back to polling if no jobs are running
        if self._running == 0:
            self.update_status(AGENT_POLLING)

    @staticmethod
    def _get_gpus():
        from collections import Counter
        from wandb.vendor.pynvml import pynvml

        try:
            pynvml.nvmlInit()
        except pynvml.NVMLError:
            gpu_names = []
        else:
            gpu_count = pynvml.nvmlDeviceGetCount()
            gpus = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(gpu_count)]
            gpu_names = [pynvml.nvmlDeviceGetName(gpu).decode("utf8") for gpu in gpus]
        finally:
            gpus = Counter(gpu_names)

        # Get just the first GPU name and count
        if gpus:
            name, count = next(iter(gpus.items()))
            return {"name": name, "count": count}
        return {}

    def _get_system_resource_defaults(self):
        import psutil

        resources = {
            "cpus": psutil.cpu_count(),
            "gpus": self._get_gpus().get("count", 0),
            "ram": psutil.virtual_memory().total / (1024**3),
        }

        return {k: v for k, v in resources.items() if v is not None}

    def _configure_runners(self, config):
        system_resource_defaults = self._get_system_resource_defaults()

        for runner in config["runners"]:
            if runner["type"] in {"kubernetes", "sagemaker"}:
                pass
            elif runner["type"] in {"local-process", "local-container"}:
                # add default resources if required
                if "resources" not in runner:
                    runner["resources"] = {}
                for resource, constraint in system_resource_defaults.items():
                    if resource not in VALID_RESOURCES:
                        raise ValueError(
                            f"Expected resources to be one of {VALID_RESOURCES}, but got {resource}"
                        )
                    if resource not in runner["resources"]:
                        runner["resources"][resource] = constraint

                # add default labels if required
                gpu_labels = self._get_gpus().get("name")
                gpu_labels = [gpu_labels] if gpu_labels else []

                if "labels" not in runner:
                    runner["labels"] = []
                for lbl in gpu_labels:
                    if lbl not in runner["labels"]:
                        runner["labels"].append(lbl)
            else:
                raise ValueError(
                    f"Expected runner type to be one of {VALID_RUNNER_TYPES} but got {runner}"
                )
        return config["runners"]

    def _get_valid_run_queues(self) -> List[RunQueue]:
        """
        Given an entity, return a list of run queues associated with that entity.
        """
        run_queues = self._api.get_run_queues_by_entity(self._entity)
        valid_queues = []

        for q in run_queues:
            config = q["config"]
            if config is None:
                valid_queues.append(q)
                continue
            else:
                config = json.loads(config)
                q["config"] = config
            runner = next(iter(config))
            if runner in self._configured_runners:
                valid = runner_dispatch[runner]
                if valid(agent=self, queue=q):
                    valid_queues.append(q)
            else:
                wandb.termwarn(f"Unsupported runner: ({runner})")
                continue
        return valid_queues

    def _order_queues_by_priority(self) -> None:
        """
        `Smartly` select a queue!
        """
        random.shuffle(self._queues)  # So smart!

    def _get_combined_job_config(self):
        self._order_queues_by_priority()

        if self._queues:
            for q in self._queues:
                try:
                    selected_queue, job = q, self.pop_from_queue(q)
                except IndexError:
                    wandb.termlog(f"Queue is empty: {q}")
                else:
                    if job is not None:
                        break
            default_config = selected_queue["config"]
            if job is not None and default_config is not None:
                job["runSpec"]["resource_args"] = merge_dicts(
                    job["runSpec"]["resource_args"], default_config
                )

            return job

    def _get_current_resources_available(self):
        """
        Get current resources available based on resources requested for each job
        """
        # Starting resources
        resources_available = {
            runner["type"]: runner.get("resources")
            for runner in self._configured_runners
            if runner["type"] not in {"kubernetes", "sagemaker"}
        }

        # Resources consumed by running jobs
        for j in self._jobs.values():
            resource_args = j.job_spec["runSpec"].get("resource_args", {})
            for runner_type, requirements in resource_args.items():
                for resource, value in requirements.items():
                    resources_available[runner_type][resource] -= value
        return resources_available

    def _resources_available_for_this_job(self, job):
        """
        Check if there are sufficient resources available for `job`.
        """
        available = self._get_current_resources_available()
        resource_args = job["runSpec"].get("resource_args")
        for runner_type, requirements in resource_args.items():
            break
        for resource, value in requirements.items():
            if resource not in VALID_RESOURCES:
                raise ValueError(
                    f"Expected resources to be one of {VALID_RESOURCES}, but got {resource}"
                )
            if available[runner_type][resource] < value:
                return False
        return True

    def _update_finished(self, job_id: Union[int, str]) -> None:
        """Check our status enum."""
        try:
            if self._jobs[job_id].get_status().state in ["failed", "finished"]:
                self.finish_job_id(job_id)
        except Exception:
            self.finish_job_id(job_id)

    def _validate_and_fix_spec_project_entity(
        self, launch_spec: Dict[str, Any]
    ) -> None:
        """Checks if launch spec target project/entity differs from agent. Forces these values to agent's if they are set."""
        if (
            launch_spec.get("project") is not None
            and launch_spec.get("project") != self._project
        ) or (
            launch_spec.get("entity") is not None
            and launch_spec.get("entity") != self._entity
        ):
            wandb.termwarn(
                f"Launch agents only support sending runs to their own project and entity. This run will be sent to {self._entity}/{self._project}"
            )
            launch_spec["entity"] = self._entity
            launch_spec["project"] = self._project

    def run_job(self, job: Dict[str, Any]) -> None:
        """Sets up project and runs the job."""
        # TODO: logger
        wandb.termlog(f"agent: got job f{job}")
        _logger.info(f"Agent job: {job}")
        # update agent status
        self.update_status(AGENT_RUNNING)

        # parse job
        _logger.info("Parsing launch spec")
        launch_spec = job["runSpec"]
        if launch_spec.get("overrides") and isinstance(
            launch_spec["overrides"].get("args"), list
        ):
            launch_spec["overrides"]["args"] = util._user_args_to_dict(
                launch_spec["overrides"].get("args", [])
            )
        self._validate_and_fix_spec_project_entity(launch_spec)

        project = create_project_from_spec(launch_spec, self._api)
        _logger.info("Fetching and validating project...")
        project = fetch_and_validate_project(project, self._api)
        _logger.info("Fetching resource...")
        resource = launch_spec.get("resource") or "local"
        backend_config: Dict[str, Any] = {
            PROJECT_DOCKER_ARGS: {},
            PROJECT_SYNCHRONOUS: False,  # agent always runs async
        }

        backend_config["runQueueItemId"] = job["runQueueItemId"]
        _logger.info("Loading backend")
        override_build_config = launch_spec.get("build")
        override_registry_config = launch_spec.get("registry")

        build_config, registry_config = resolve_build_and_registry_config(
            self.default_config, override_build_config, override_registry_config
        )
        builder = load_builder(build_config)

        default_runner = self.default_config.get("runner", {}).get("type")
        if default_runner == resource:
            backend_config["runner"] = self.default_config.get("runner")
        backend = load_backend(resource, self._api, backend_config)
        backend.verify()
        _logger.info("Backend loaded...")
        run = backend.run(project, builder, registry_config)
        if run:
            run.job_spec = job
            self._jobs[run.id] = run
            self._running += 1

    def loop(self) -> None:
        """Main loop function for agent."""
        self.print_status()
        try:
            while True:
                self._ticks += 1
                job = None

                agent_response = self._api.get_new_launch_agent(
                    self._id, self.gorilla_supports_agents
                )
                self._name = agent_response[
                    "name"
                ]  # hacky, but we don't return the name on create so this is first time
                if agent_response["stopPolling"]:
                    # shutdown process and all jobs if requested from ui
                    raise KeyboardInterrupt
                if self._running < self._max_jobs:
                    # only check for new jobs if we're not at max
                    job = self._get_combined_job_config()
                    if job:
                        if not self._resources_available_for_this_job(job):
                            wandb.termwarn(
                                f"Resources were not available for {job['runQueueItemId']}.  Job requires {job['runSpec']['resource_args']}, but agent only has {self._get_current_resources_available()}"
                            )
                            continue
                        try:
                            self.run_job(job)
                        except Exception as e:
                            wandb.termerror(f"Error running job: {e}")
                            self._api.ack_run_queue_item(job["runQueueItemId"])
                for job_id in self.job_ids:
                    self._update_finished(job_id)
                if self._ticks % 2 == 0:
                    if self._running == 0:
                        self.update_status(AGENT_POLLING)
                        self.print_status()
                    else:
                        self.update_status(AGENT_RUNNING)
                time.sleep(AGENT_POLLING_INTERVAL)

        except KeyboardInterrupt:
            # temp: for local, kill all jobs. we don't yet have good handling for different
            # types of runners in general
            for _, run in self._jobs.items():
                if isinstance(run, LocalSubmittedRun):
                    run.command_proc.kill()
            self.update_status(AGENT_KILLED)
            wandb.termlog("Shutting down, active jobs:")
            self.print_status()
