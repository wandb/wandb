"""W&B Public API for management Launch Jobs and Launch Queues.

This module provides classes for managing W&B jobs, queued runs, and run
queues.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import TYPE_CHECKING, Any, Literal, Mapping

from wandb_gql import gql

import wandb
from wandb import util
from wandb.apis import public
from wandb.apis.normalize import normalize_exceptions
from wandb.errors import CommError
from wandb.sdk.artifacts.artifact_state import ArtifactState
from wandb.sdk.data_types._dtypes import InvalidType, Type, TypeRegistry
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import (
    LAUNCH_DEFAULT_PROJECT,
    _fetch_git_repo,
    apply_patch,
    convert_jupyter_notebook_to_script,
)

if TYPE_CHECKING:
    from wandb.apis.public import Api, RetryingClient


class Job:
    _name: str
    _input_types: Type
    _output_types: Type
    _entity: str
    _project: str
    _entrypoint: list[str]
    _notebook_job: bool
    _partial: bool

    def __init__(self, api: Api, name, path: str | None = None) -> None:
        try:
            self._job_artifact = api._artifact(name, type="job")
        except CommError:
            raise CommError(f"Job artifact {name} not found")
        if path:
            self._fpath = path
            self._job_artifact.download(root=path)
        else:
            self._fpath = self._job_artifact.download()
        self._name = name
        self._api = api
        self._entity = api.default_entity

        with open(os.path.join(self._fpath, "wandb-job.json")) as f:
            self._job_info: Mapping[str, Any] = json.load(f)
        source_info = self._job_info.get("source", {})
        # only use notebook job if entrypoint not set and notebook is set
        self._notebook_job = source_info.get("notebook", False)
        self._entrypoint = source_info.get("entrypoint")
        self._dockerfile = source_info.get("dockerfile")
        self._build_context = source_info.get("build_context")
        self._base_image = source_info.get("base_image")
        self._args = source_info.get("args")
        self._partial = self._job_info.get("_partial", False)
        self._requirements_file = os.path.join(self._fpath, "requirements.frozen.txt")
        self._input_types = TypeRegistry.type_from_dict(
            self._job_info.get("input_types")
        )
        self._output_types = TypeRegistry.type_from_dict(
            self._job_info.get("output_types")
        )
        if self._job_info.get("source_type") == "artifact":
            self._set_configure_launch_project(self._configure_launch_project_artifact)
        if self._job_info.get("source_type") == "repo":
            self._set_configure_launch_project(self._configure_launch_project_repo)
        if self._job_info.get("source_type") == "image":
            self._set_configure_launch_project(self._configure_launch_project_container)

    @property
    def name(self):
        """The name of the job."""
        return self._name

    def _set_configure_launch_project(self, func):
        self.configure_launch_project = func

    def _get_code_artifact(self, artifact_string):
        artifact_string, base_url, is_id = util.parse_artifact_string(artifact_string)
        if is_id:
            code_artifact = wandb.Artifact._from_id(artifact_string, self._api._client)
        else:
            code_artifact = self._api._artifact(name=artifact_string, type="code")
        if code_artifact is None:
            raise LaunchError("No code artifact found")
        if code_artifact.state == ArtifactState.DELETED:
            raise LaunchError(
                f"Job {self.name} references deleted code artifact {code_artifact.name}"
            )
        return code_artifact

    def _configure_launch_project_notebook(self, launch_project):
        new_fname = convert_jupyter_notebook_to_script(
            self._entrypoint[-1], launch_project.project_dir
        )
        new_entrypoint = self._entrypoint
        new_entrypoint[-1] = new_fname
        launch_project.set_job_entry_point(new_entrypoint)

    def _configure_launch_project_repo(self, launch_project):
        git_info = self._job_info.get("source", {}).get("git", {})
        _fetch_git_repo(
            launch_project.project_dir,
            git_info["remote"],
            git_info["commit"],
        )
        if os.path.exists(os.path.join(self._fpath, "diff.patch")):
            with open(os.path.join(self._fpath, "diff.patch")) as f:
                apply_patch(f.read(), launch_project.project_dir)
        shutil.copy(self._requirements_file, launch_project.project_dir)
        launch_project.python_version = self._job_info.get("runtime")
        if self._notebook_job:
            self._configure_launch_project_notebook(launch_project)
        else:
            launch_project.set_job_entry_point(self._entrypoint)

        if self._dockerfile:
            launch_project.set_job_dockerfile(self._dockerfile)
        if self._build_context:
            launch_project.set_job_build_context(self._build_context)
        if self._base_image:
            launch_project.set_job_base_image(self._base_image)

    def _configure_launch_project_artifact(self, launch_project):
        artifact_string = self._job_info.get("source", {}).get("artifact")
        if artifact_string is None:
            raise LaunchError(f"Job {self.name} had no source artifact")

        code_artifact = self._get_code_artifact(artifact_string)
        launch_project.python_version = self._job_info.get("runtime")
        shutil.copy(self._requirements_file, launch_project.project_dir)

        code_artifact.download(launch_project.project_dir)

        if self._notebook_job:
            self._configure_launch_project_notebook(launch_project)
        else:
            launch_project.set_job_entry_point(self._entrypoint)

        if self._dockerfile:
            launch_project.set_job_dockerfile(self._dockerfile)
        if self._build_context:
            launch_project.set_job_build_context(self._build_context)
        if self._base_image:
            launch_project.set_job_base_image(self._base_image)

    def _configure_launch_project_container(self, launch_project):
        launch_project.docker_image = self._job_info.get("source", {}).get("image")
        if launch_project.docker_image is None:
            raise LaunchError(
                "Job had malformed source dictionary without an image key"
            )
        if self._entrypoint:
            launch_project.set_job_entry_point(self._entrypoint)

    def set_entrypoint(self, entrypoint: list[str]):
        """Set the entrypoint for the job."""
        self._entrypoint = entrypoint

    def call(
        self,
        config,
        project=None,
        entity=None,
        queue=None,
        resource="local-container",
        resource_args=None,
        template_variables=None,
        project_queue=None,
        priority=None,
    ):
        """Call the job with the given configuration.

        Args:
            config (dict): The configuration to pass to the job.
                This should be a dictionary containing key-value pairs that
                match the input types defined in the job.
            project (str, optional): The project to log the run to. Defaults
                to the job's project.
            entity (str, optional): The entity to log the run under. Defaults
                to the job's entity.
            queue (str, optional): The name of the queue to enqueue the job to.
                Defaults to None.
            resource (str, optional): The resource type to use for execution.
                Defaults to "local-container".
            resource_args (dict, optional): Additional arguments for the
                resource type. Defaults to None.
            template_variables (dict, optional): Template variables to use for
                the job. Defaults to None.
            project_queue (str, optional): The project that manages the queue.
                Defaults to None.
            priority (int, optional): The priority of the queued run.
                Defaults to None.
        """
        from wandb.sdk.launch import _launch_add

        run_config = {}
        for key, item in config.items():
            if util._is_artifact_object(item):
                if isinstance(item, wandb.Artifact) and item.is_draft():
                    raise ValueError("Cannot queue jobs with unlogged artifacts")
                run_config[key] = util.artifact_to_json(item)

        run_config.update(config)

        assigned_config_type = self._input_types.assign(run_config)
        if self._partial:
            wandb.termwarn(
                "Launching manually created job for the first time, can't verify types"
            )
        else:
            if isinstance(assigned_config_type, InvalidType):
                raise TypeError(self._input_types.explain(run_config))

        queued_run = _launch_add.launch_add(
            job=self._name,
            config={"overrides": {"run_config": run_config}},
            template_variables=template_variables,
            project=project or self._project,
            entity=entity or self._entity,
            queue_name=queue,
            resource=resource,
            project_queue=project_queue,
            resource_args=resource_args,
            priority=priority,
        )
        return queued_run


class QueuedRun:
    """A single queued run associated with an entity and project.

    Args:
        entity: The entity associated with the queued run.
        project (str): The project where runs executed by the queue are logged to.
        queue_name (str): The name of the queue.
        run_queue_item_id (int): The id of the run queue item.
        project_queue (str): The project that manages the queue.
        priority (str): The priority of the queued run.

    Call `run = queued_run.wait_until_running()` or
    `run = queued_run.wait_until_finished()` to access the run.
    """

    def __init__(
        self,
        client,
        entity,
        project,
        queue_name,
        run_queue_item_id,
        project_queue=LAUNCH_DEFAULT_PROJECT,
        priority=None,
    ):
        self.client = client
        self._entity = entity
        self._project = project
        self._queue_name = queue_name
        self._run_queue_item_id = run_queue_item_id
        self.sweep = None
        self._run = None
        self.project_queue = project_queue
        self.priority = priority

    @property
    def queue_name(self):
        """The name of the queue."""
        return self._queue_name

    @property
    def id(self):
        """The id of the queued run."""
        return self._run_queue_item_id

    @property
    def project(self):
        """The project associated with the queued run."""
        return self._project

    @property
    def entity(self):
        """The entity associated with the queued run."""
        return self._entity

    @property
    def state(self):
        """The state of the queued run."""
        item = self._get_item()
        if item:
            return item["state"].lower()

        raise ValueError(
            f"Could not find QueuedRunItem associated with id: {self.id} on queue {self.queue_name} at itemId: {self.id}"
        )

    @normalize_exceptions
    def _get_run_queue_item_legacy(self) -> dict:
        query = gql(
            """
            query GetRunQueueItem($projectName: String!, $entityName: String!, $runQueue: String!) {
                project(name: $projectName, entityName: $entityName) {
                    runQueue(name:$runQueue) {
                        runQueueItems {
                            edges {
                                node {
                                    id
                                    state
                                    associatedRunId
                                }
                            }
                        }
                    }
                }
            }
            """
        )
        variable_values = {
            "projectName": self.project_queue,
            "entityName": self._entity,
            "runQueue": self.queue_name,
        }
        res = self.client.execute(query, variable_values)

        for item in res["project"]["runQueue"]["runQueueItems"]["edges"]:
            if str(item["node"]["id"]) == str(self.id):
                return item["node"]

    @normalize_exceptions
    def _get_item(self):
        query = gql(
            """
            query GetRunQueueItem($projectName: String!, $entityName: String!, $runQueue: String!, $itemId: ID!) {
                project(name: $projectName, entityName: $entityName) {
                    runQueue(name: $runQueue) {
                        runQueueItem(id: $itemId) {
                            id
                            state
                            associatedRunId
                        }
                    }
                }
            }
        """
        )
        variable_values = {
            "projectName": self.project_queue,
            "entityName": self._entity,
            "runQueue": self.queue_name,
            "itemId": self.id,
        }
        try:
            res = self.client.execute(query, variable_values)  # exception w/ old server
            if res["project"]["runQueue"].get("runQueueItem") is not None:
                return res["project"]["runQueue"]["runQueueItem"]
        except Exception as e:
            if "Cannot query field" not in str(e):
                raise LaunchError(f"Unknown exception: {e}")

        return self._get_run_queue_item_legacy()

    @normalize_exceptions
    def wait_until_finished(self):
        """Wait for the queued run to complete and return the finished run."""
        if not self._run:
            self.wait_until_running()

        self._run.wait_until_finished()
        # refetch run to get updated summary
        self._run.load(force=True)
        return self._run

    @normalize_exceptions
    def delete(self, delete_artifacts=False):
        """Delete the given queued run from the wandb backend."""
        query = gql(
            """
            query fetchRunQueuesFromProject($entityName: String!, $projectName: String!, $runQueueName: String!) {
                project(name: $projectName, entityName: $entityName) {
                    runQueue(name: $runQueueName) {
                        id
                    }
                }
            }
            """
        )

        res = self.client.execute(
            query,
            variable_values={
                "entityName": self.entity,
                "projectName": self.project_queue,
                "runQueueName": self.queue_name,
            },
        )

        if res["project"].get("runQueue") is not None:
            queue_id = res["project"]["runQueue"]["id"]

        mutation = gql(
            """
            mutation DeleteFromRunQueue(
                $queueID: ID!,
                $runQueueItemId: ID!
            ) {
                deleteFromRunQueue(input: {
                    queueID: $queueID
                    runQueueItemId: $runQueueItemId
                }) {
                    success
                    clientMutationId
                }
            }
            """
        )
        self.client.execute(
            mutation,
            variable_values={
                "queueID": queue_id,
                "runQueueItemId": self._run_queue_item_id,
            },
        )

    @normalize_exceptions
    def wait_until_running(self):
        """Wait until the queued run is running and return the run."""
        if self._run is not None:
            return self._run

        while True:
            # sleep here to hide an ugly warning
            time.sleep(2)
            item = self._get_item()
            if item and item["associatedRunId"] is not None:
                try:
                    self._run = public.Run(
                        self.client,
                        self._entity,
                        self.project,
                        item["associatedRunId"],
                        None,
                    )
                    self._run_id = item["associatedRunId"]
                except ValueError as e:
                    wandb.termwarn(str(e))
                else:
                    return self._run
            elif item:
                wandb.termlog("Waiting for run to start")

            time.sleep(3)

    def __repr__(self):
        return f"<QueuedRun {self.queue_name} ({self.id})"


RunQueueResourceType = Literal[
    "local-container", "local-process", "kubernetes", "sagemaker", "gcp-vertex"
]
RunQueueAccessType = Literal["project", "user"]
RunQueuePrioritizationMode = Literal["DISABLED", "V0"]


class RunQueue:
    """Class that represents a run queue in W&B.

    Args:
        client: W&B API client instance.
        name: Name of the run queue
        entity: The entity (user or team) that owns this queue
        prioritization_mode: Queue priority mode
            Can be "DISABLED" or "V0". Defaults to `None`.
        _access: Access level for the queue
            Can be "project" or "user". Defaults to `None`.
        _default_resource_config_id: ID of default resource config
        _default_resource_config: Default resource configuration
    """

    def __init__(
        self,
        client: RetryingClient,
        name: str,
        entity: str,
        prioritization_mode: RunQueuePrioritizationMode | None = None,
        _access: RunQueueAccessType | None = None,
        _default_resource_config_id: int | None = None,
        _default_resource_config: dict | None = None,
    ) -> None:
        self._name: str = name
        self._client = client
        self._entity = entity
        self._prioritization_mode = prioritization_mode
        self._access = _access
        self._default_resource_config_id = _default_resource_config_id
        self._default_resource_config = _default_resource_config
        self._template_variables = None
        self._type = None
        self._items = None
        self._id = None

    @property
    def name(self):
        """The name of the queue."""
        return self._name

    @property
    def entity(self):
        """The entity that owns the queue."""
        return self._entity

    @property
    def prioritization_mode(self) -> RunQueuePrioritizationMode:
        """The prioritization mode of the queue.

        Can be set to "DISABLED" or "V0".
        """
        if self._prioritization_mode is None:
            self._get_metadata()
        return self._prioritization_mode

    @property
    def access(self) -> RunQueueAccessType:
        """The access level of the queue."""
        if self._access is None:
            self._get_metadata()
        return self._access

    @property
    def external_links(self) -> dict[str, str]:
        """External resource links for the queue."""
        if self._external_links is None:
            self._get_metadata()
        return self._external_links

    @property
    def type(self) -> RunQueueResourceType:
        """The resource type for execution."""
        if self._type is None:
            if self._default_resource_config_id is None:
                self._get_metadata()
            self._get_default_resource_config()
        return self._type

    @property
    def default_resource_config(self):
        """The default configuration for resources."""
        if self._default_resource_config is None:
            if self._default_resource_config_id is None:
                self._get_metadata()
            self._get_default_resource_config()
        return self._default_resource_config

    @property
    def template_variables(self):
        """Variables for resource templates."""
        if self._template_variables is None:
            if self._default_resource_config_id is None:
                self._get_metadata()
            self._get_default_resource_config()
        return self._template_variables

    @property
    def id(self) -> str:
        """The id of the queue."""
        if self._id is None:
            self._get_metadata()
        return self._id

    @property
    def items(self) -> list[QueuedRun]:
        """Up to the first 100 queued runs. Modifying this list will not modify the queue or any enqueued items!"""
        # TODO(np): Add a paginated interface
        if self._items is None:
            self._get_items()
        return self._items

    @normalize_exceptions
    def delete(self):
        """Delete the run queue from the wandb backend."""
        query = gql(
            """
            mutation DeleteRunQueue($id: ID!) {
                deleteRunQueues(input: {queueIDs: [$id]}) {
                    success
                    clientMutationId
                }
            }
            """
        )
        variable_values = {"id": self.id}
        res = self._client.execute(query, variable_values)
        if res["deleteRunQueues"]["success"]:
            self._id = None
            self._access = None
            self._default_resource_config_id = None
            self._default_resource_config = None
            self._items = None
        else:
            raise CommError(f"Failed to delete run queue {self.name}")

    def __repr__(self):
        return f"<RunQueue {self._entity}/{self._name}>"

    @normalize_exceptions
    def _get_metadata(self):
        query = gql(
            """
            query GetRunQueueMetadata($projectName: String!, $entityName: String!, $runQueue: String!) {
                project(name: $projectName, entityName: $entityName) {
                    runQueue(name: $runQueue) {
                        id
                        access
                        defaultResourceConfigID
                        prioritizationMode
                        externalLinks
                    }
                }
            }
        """
        )
        variable_values = {
            "projectName": LAUNCH_DEFAULT_PROJECT,
            "entityName": self._entity,
            "runQueue": self._name,
        }
        res = self._client.execute(query, variable_values)
        self._id = res["project"]["runQueue"]["id"]
        self._access = res["project"]["runQueue"]["access"]
        self._default_resource_config_id = res["project"]["runQueue"][
            "defaultResourceConfigID"
        ]
        self._external_links = res["project"]["runQueue"]["externalLinks"]
        if self._default_resource_config_id is None:
            self._default_resource_config = {}
        self._prioritization_mode = res["project"]["runQueue"]["prioritizationMode"]

    @normalize_exceptions
    def _get_default_resource_config(self):
        query = gql(
            """
            query GetDefaultResourceConfig($entityName: String!, $id: ID!) {
                entity(name: $entityName) {
                    defaultResourceConfig(id: $id) {
                        config
                        resource
                        templateVariables {
                            name
                            schema
                        }
                    }
                }
            }
        """
        )
        variable_values = {
            "entityName": self._entity,
            "id": self._default_resource_config_id,
        }
        res = self._client.execute(query, variable_values)
        self._type = res["entity"]["defaultResourceConfig"]["resource"]
        self._default_resource_config = res["entity"]["defaultResourceConfig"]["config"]
        self._template_variables = res["entity"]["defaultResourceConfig"][
            "templateVariables"
        ]

    @normalize_exceptions
    def _get_items(self):
        query = gql(
            """
            query GetRunQueueItems($projectName: String!, $entityName: String!, $runQueue: String!) {
                project(name: $projectName, entityName: $entityName) {
                    runQueue(name: $runQueue) {
                        runQueueItems(first: 100) {
                            edges {
                                node {
                                    id
                                }
                            }
                        }
                    }
                }
            }
        """
        )
        variable_values = {
            "projectName": LAUNCH_DEFAULT_PROJECT,
            "entityName": self._entity,
            "runQueue": self._name,
        }
        res = self._client.execute(query, variable_values)
        self._items = []
        for item in res["project"]["runQueue"]["runQueueItems"]["edges"]:
            self._items.append(
                QueuedRun(
                    self._client,
                    self._entity,
                    LAUNCH_DEFAULT_PROJECT,
                    self._name,
                    item["node"]["id"],
                )
            )

    @classmethod
    def create(
        cls,
        name: str,
        resource: RunQueueResourceType,
        entity: str | None = None,
        prioritization_mode: RunQueuePrioritizationMode | None = None,
        config: dict | None = None,
        template_variables: dict | None = None,
    ) -> RunQueue:
        """Create a RunQueue.

        Args:
            name: The name of the run queue to create.
            resource: The resource type for execution.
            entity: The entity (user or team) that will own the queue.
                Defaults to the default entity of the API client.
            prioritization_mode: The prioritization mode for the queue.
                Can be "DISABLED" or "V0". Defaults to None.
            config: Optional dictionary for the default resource
                configuration. Defaults to None.
            template_variables: Optional dictionary for template variables
                used in the resource configuration.
        """
        public_api = Api()
        return public_api.create_run_queue(
            name, resource, entity, prioritization_mode, config, template_variables
        )
