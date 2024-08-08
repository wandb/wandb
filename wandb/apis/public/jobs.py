"""Public API: jobs."""

import json
import os
import shutil
import sys
import time
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

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
    _entrypoint: List[str]
    _notebook_job: bool
    _partial: bool

    def __init__(self, api: "Api", name, path: Optional[str] = None) -> None:
        try:
            self._job_artifact = api.artifact(name, type="job")
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
        return self._name

    def _set_configure_launch_project(self, func):
        self.configure_launch_project = func

    def _get_code_artifact(self, artifact_string):
        artifact_string, base_url, is_id = util.parse_artifact_string(artifact_string)
        if is_id:
            code_artifact = wandb.Artifact._from_id(artifact_string, self._api._client)
        else:
            code_artifact = self._api.artifact(name=artifact_string, type="code")
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

    def set_entrypoint(self, entrypoint: List[str]):
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
    """A single queued run associated with an entity and project. Call `run = queued_run.wait_until_running()` or `run = queued_run.wait_until_finished()` to access the run."""

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
        return self._queue_name

    @property
    def id(self):
        return self._run_queue_item_id

    @property
    def project(self):
        return self._project

    @property
    def entity(self):
        return self._entity

    @property
    def state(self):
        item = self._get_item()
        if item:
            return item["state"].lower()

        raise ValueError(
            f"Could not find QueuedRunItem associated with id: {self.id} on queue {self.queue_name} at itemId: {self.id}"
        )

    @normalize_exceptions
    def _get_run_queue_item_legacy(self) -> Dict:
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
                    return self._run
                except ValueError as e:
                    print(e)
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
    def __init__(
        self,
        client: "RetryingClient",
        name: str,
        entity: str,
        prioritization_mode: Optional[RunQueuePrioritizationMode] = None,
        _access: Optional[RunQueueAccessType] = None,
        _default_resource_config_id: Optional[int] = None,
        _default_resource_config: Optional[dict] = None,
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
        return self._name

    @property
    def entity(self):
        return self._entity

    @property
    def prioritization_mode(self) -> RunQueuePrioritizationMode:
        if self._prioritization_mode is None:
            self._get_metadata()
        return self._prioritization_mode

    @property
    def access(self) -> RunQueueAccessType:
        if self._access is None:
            self._get_metadata()
        return self._access

    @property
    def type(self) -> RunQueueResourceType:
        if self._type is None:
            if self._default_resource_config_id is None:
                self._get_metadata()
            self._get_default_resource_config()
        return self._type

    @property
    def default_resource_config(self):
        if self._default_resource_config is None:
            if self._default_resource_config_id is None:
                self._get_metadata()
            self._get_default_resource_config()
        return self._default_resource_config

    @property
    def template_variables(self):
        if self._template_variables is None:
            if self._default_resource_config_id is None:
                self._get_metadata()
            self._get_default_resource_config()
        return self._template_variables

    @property
    def id(self) -> str:
        if self._id is None:
            self._get_metadata()
        return self._id

    @property
    def items(self) -> List[QueuedRun]:
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
        resource: "RunQueueResourceType",
        entity: Optional[str] = None,
        prioritization_mode: Optional["RunQueuePrioritizationMode"] = None,
        config: Optional[dict] = None,
        template_variables: Optional[dict] = None,
    ) -> "RunQueue":
        public_api = Api()
        return public_api.create_run_queue(
            name, resource, entity, prioritization_mode, config, template_variables
        )
