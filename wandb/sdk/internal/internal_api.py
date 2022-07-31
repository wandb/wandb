from abc import ABC
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Sequence,
    TextIO,
    Tuple,
    TypeVar,
    Optional,
    Union,
)
from wandb_gql import Client, gql  # type: ignore
from wandb_gql.client import RetryError  # type: ignore
from wandb_gql.transport.requests import RequestsHTTPTransport  # type: ignore

import ast
import base64
from copy import deepcopy
import datetime
from io import BytesIO
import json
import os
from pkg_resources import parse_version
import re
import requests
import logging
import socket
import sys

import click
import yaml

import wandb
from wandb import __version__
from wandb import env
from wandb.old.settings import Settings
from wandb import util
from wandb.apis.normalize import normalize_exceptions
from wandb.errors import CommError, UsageError
from wandb.integration.sagemaker import parse_sm_secrets
from ..lib import retry
from ..lib.filenames import DIFF_FNAME, METADATA_FNAME
from ..lib.git import GitRepo

from .progress import Progress

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    if sys.version_info >= (3, 8):
        from typing import Literal, Protocol, TypedDict
    else:
        from typing_extensions import Literal, Protocol, TypedDict

    from .progress import ProgressFn

    class CreateArtifactFileSpecInput(TypedDict):
        """Corresponds to `type CreateArtifactFileSpecInput` in schema.graphql"""

        artifactID: str
        name: str
        md5: str
        mimetype: Optional[str]
        artifactManifestID: Optional[str]

    class DefaultSettings(TypedDict):
        section: str
        git_remote: str
        ignore_globs: Optional[List[str]]
        base_url: Optional[str]
        root_dir: Optional[str]
        api_key: Optional[str]
        entity: Optional[str]
        project: Optional[str]

    _Response = TypeVar("_Response", bound=MutableMapping)
    _ArtifactVersion = TypeVar("_ArtifactVersion", bound=MutableMapping)
    SweepState = Literal["RUNNING", "PAUSED", "CANCELED", "FINISHED"]
    Number = Union[int, float]


# class _MappingSupportsCopy(Protocol):
#     def copy(self) -> "_MappingSupportsCopy": ...
#     def keys(self) -> Iterable: ...
#     def __getitem__(self, name: str) -> Any: ...


class Api:
    """W&B Internal Api wrapper

    Note:
        Settings are automatically overridden by looking for
        a `wandb/settings` file in the current working directory or its parent
        directory. If none can be found, we look in the current user's home
        directory.

    Arguments:
        default_settings(dict, optional): If you aren't using a settings
        file, or you wish to override the section to use in the settings file
        Override the settings here.
    """

    HTTP_TIMEOUT = env.get_http_timeout(10)

    def __init__(
        self,
        default_settings: Optional[
            Union[
                "wandb.sdk.wandb_settings.Settings",
                "wandb.sdk.internal.settings_static.SettingsStatic",
                Settings,
                dict,
            ]
        ] = None,
        load_settings: bool = True,
        retry_timedelta: datetime.timedelta = datetime.timedelta(days=7),
        environ: MutableMapping = os.environ,
        retry_callback: Optional[Callable[[int, str], Any]] = None,
    ) -> None:
        self._environ = environ
        self.default_settings: "DefaultSettings" = {
            "section": "default",
            "git_remote": "origin",
            "ignore_globs": [],
            "base_url": "https://api.wandb.ai",
            "root_dir": None,
            "api_key": None,
            "entity": None,
            "project": None,
        }
        self.retry_timedelta = retry_timedelta
        # todo: Old Settings do not follow the SupportsKeysAndGetItem Protocol
        self.default_settings.update(default_settings or {})  # type: ignore
        self.retry_uploads = 10
        self._settings = Settings(
            load_settings=load_settings,
            root_dir=self.default_settings.get("root_dir"),
        )
        self.git = GitRepo(remote=self.settings("git_remote"))
        # Mutable settings set by the _file_stream_api
        self.dynamic_settings = {
            "system_sample_seconds": 2,
            "system_samples": 15,
            "heartbeat_seconds": 30,
        }
        self.client = Client(
            transport=RequestsHTTPTransport(
                headers={
                    "User-Agent": self.user_agent,
                    "X-WANDB-USERNAME": env.get_username(env=self._environ),
                    "X-WANDB-USER-EMAIL": env.get_user_email(env=self._environ),
                },
                use_json=True,
                # this timeout won't apply when the DNS lookup fails. in that case, it will be 60s
                # https://bugs.python.org/issue22889
                timeout=self.HTTP_TIMEOUT,
                auth=("api", self.api_key or ""),
                url=f"{self.settings('base_url')}/graphql",
            )
        )
        self.retry_callback = retry_callback
        self.gql = retry.Retry(
            self.execute,
            retry_timedelta=retry_timedelta,
            check_retry_fn=util.no_retry_auth,
            retryable_exceptions=(RetryError, requests.RequestException),
            retry_callback=retry_callback,
        )
        self._current_run_id: Optional[str] = None
        self._file_stream_api = None
        # This Retry class is initialized once for each Api instance, so this
        # defaults to retrying 1 million times per process or 7 days
        self.upload_file_retry = normalize_exceptions(
            retry.retriable(retry_timedelta=retry_timedelta)(self.upload_file)
        )
        self._client_id_mapping: Dict[str, str] = {}
        # Large file uploads to azure can optionally use their SDK
        self._azure_blob_module = util.get_module("azure.storage.blob")

        self.query_types: Optional[List[str]] = None
        self.server_info_types: Optional[List[str]] = None
        self.server_use_artifact_input_info: Optional[List[str]] = None
        self._max_cli_version: Optional[str] = None
        self._server_settings_type: Optional[List[str]] = None

    def reauth(self) -> None:
        """Ensures the current api key is set in the transport"""
        self.client.transport.auth = ("api", self.api_key or "")

    def relocate(self) -> None:
        """Ensures the current api points to the right server"""
        self.client.transport.url = "%s/graphql" % self.settings("base_url")

    def execute(self, *args: Any, **kwargs: Any) -> "_Response":
        """Wrapper around execute that logs in cases of failure."""
        try:
            return self.client.execute(*args, **kwargs)  # type: ignore
        except requests.exceptions.HTTPError as err:
            res = err.response
            logger.error(f"{res.status_code} response executing GraphQL.")
            logger.error(res.text)
            self.display_gorilla_error_if_found(res)
            raise

    def display_gorilla_error_if_found(self, res: requests.Response) -> None:
        try:
            data = res.json()
        except ValueError:
            return

        if "errors" in data and isinstance(data["errors"], list):
            for err in data["errors"]:
                # Our tests and potentially some api endpoints return a string error?
                if isinstance(err, str):
                    err = {"message": err}
                if not err.get("message"):
                    continue
                wandb.termerror(
                    "Error while calling W&B API: {} ({})".format(err["message"], res)
                )

    def disabled(self) -> Union[str, bool]:
        return self._settings.get(Settings.DEFAULT_SECTION, "disabled", fallback=False)  # type: ignore

    def set_current_run_id(self, run_id: str) -> None:
        self._current_run_id = run_id

    @property
    def current_run_id(self) -> Optional[str]:
        return self._current_run_id

    @property
    def user_agent(self) -> str:
        return f"W&B Internal Client {__version__}"

    @property
    def api_key(self) -> Optional[str]:
        auth = requests.utils.get_netrc_auth(self.api_url)
        key = None
        if auth:
            key = auth[-1]

        # Environment should take precedence
        env_key: Optional[str] = self._environ.get(env.API_KEY)
        sagemaker_key: Optional[str] = parse_sm_secrets().get(env.API_KEY)
        default_key: Optional[str] = self.default_settings.get("api_key")
        return env_key or key or sagemaker_key or default_key

    @property
    def api_url(self) -> str:
        return self.settings("base_url")  # type: ignore

    @property
    def app_url(self) -> str:
        return wandb.util.app_url(self.api_url)

    @property
    def default_entity(self) -> str:
        return self.viewer().get("entity")  # type: ignore

    def settings(self, key: Optional[str] = None, section: Optional[str] = None) -> Any:
        """The settings overridden from the wandb/settings file.

        Arguments:
            key (str, optional): If provided only this setting is returned
            section (str, optional): If provided this section of the setting file is
            used, defaults to "default"

        Returns:
            A dict with the current settings

                {
                    "entity": "models",
                    "base_url": "https://api.wandb.ai",
                    "project": None
                }
        """
        result = self.default_settings.copy()
        result.update(self._settings.items(section=section))  # type: ignore
        result.update(
            {
                "entity": env.get_entity(
                    self._settings.get(
                        Settings.DEFAULT_SECTION,
                        "entity",
                        fallback=result.get("entity"),
                    ),
                    env=self._environ,
                ),
                "project": env.get_project(
                    self._settings.get(
                        Settings.DEFAULT_SECTION,
                        "project",
                        fallback=result.get("project"),
                    ),
                    env=self._environ,
                ),
                "base_url": env.get_base_url(
                    self._settings.get(
                        Settings.DEFAULT_SECTION,
                        "base_url",
                        fallback=result.get("base_url"),
                    ),
                    env=self._environ,
                ),
                "ignore_globs": env.get_ignore(
                    self._settings.get(
                        Settings.DEFAULT_SECTION,
                        "ignore_globs",
                        fallback=result.get("ignore_globs"),
                    ),
                    env=self._environ,
                ),
            }
        )

        return result if key is None else result[key]  # type: ignore

    def clear_setting(
        self, key: str, globally: bool = False, persist: bool = False
    ) -> None:
        self._settings.clear(
            Settings.DEFAULT_SECTION, key, globally=globally, persist=persist
        )

    def set_setting(
        self, key: str, value: Any, globally: bool = False, persist: bool = False
    ) -> None:
        self._settings.set(
            Settings.DEFAULT_SECTION, key, value, globally=globally, persist=persist
        )
        if key == "entity":
            env.set_entity(value, env=self._environ)
        elif key == "project":
            env.set_project(value, env=self._environ)
        elif key == "base_url":
            self.relocate()

    def parse_slug(
        self, slug: str, project: Optional[str] = None, run: Optional[str] = None
    ) -> Tuple[str, str]:
        """Parses a slug into a project and run.

        Arguments:
            slug (str): The slug to parse
            project (str, optional): The project to use, if not provided it will be
            inferred from the slug
            run (str, optional): The run to use, if not provided it will be inferred
            from the slug

        Returns:
            A dict with the project and run
        """
        if slug and "/" in slug:
            parts = slug.split("/")
            project = parts[0]
            run = parts[1]
        else:
            project = project or self.settings().get("project")
            if project is None:
                raise CommError("No default project configured.")
            run = run or slug or self.current_run_id or env.get_run(env=self._environ)
            assert run, "run must be specified"
        return project, run

    @normalize_exceptions
    def server_info_introspection(self) -> Tuple[List[str], List[str]]:
        query_string = """
           query ProbeServerCapabilities {
               QueryType: __type(name: "Query") {
                   ...fieldData
                }
               ServerInfoType: __type(name: "ServerInfo") {
                   ...fieldData
                }
            }

            fragment fieldData on __Type {
                fields {
                    name
                }
            }
        """
        if self.query_types is None or self.server_info_types is None:
            query = gql(query_string)
            res = self.gql(query)

            self.query_types = [
                field.get("name", "")
                for field in res.get("QueryType", {}).get("fields", [{}])
            ]
            self.server_info_types = [
                field.get("name", "")
                for field in res.get("ServerInfoType", {}).get("fields", [{}])
            ]
        return self.query_types, self.server_info_types

    @normalize_exceptions
    def server_settings_introspection(self) -> None:
        query_string = """
           query ProbeServerSettings {
               ServerSettingsType: __type(name: "ServerSettings") {
                   ...fieldData
                }
            }

            fragment fieldData on __Type {
                fields {
                    name
                }
            }
        """
        if self._server_settings_type is None:
            query = gql(query_string)
            res = self.gql(query)
            self._server_settings_type = (
                [
                    field.get("name", "")
                    for field in res.get("ServerSettingsType", {}).get("fields", [{}])
                ]
                if res
                else []
            )

    def server_use_artifact_input_introspection(self) -> List:
        query_string = """
           query ProbeServerUseArtifactInput {
               UseArtifactInputInfoType: __type(name: "UseArtifactInput") {
                   name
                   inputFields {
                       name
                   }
                }
            }
        """

        if self.server_use_artifact_input_info is None:
            query = gql(query_string)
            res = self.gql(query)
            self.server_use_artifact_input_info = [
                field.get("name", "")
                for field in res.get("UseArtifactInputInfoType", {}).get(
                    "inputFields", [{}]
                )
            ]
        return self.server_use_artifact_input_info

    @normalize_exceptions
    def launch_agent_introspection(self) -> Optional[str]:
        query = gql(
            """
            query LaunchAgentIntrospection {
                LaunchAgentType: __type(name: "LaunchAgent") {
                    name
                }
            }
        """
        )

        res = self.gql(query)
        return res.get("LaunchAgentType") or None

    @normalize_exceptions
    def viewer(self) -> Dict[str, Any]:
        query = gql(
            """
        query Viewer{
            viewer {
                id
                entity
                flags
                teams {
                    edges {
                        node {
                            name
                        }
                    }
                }
            }
        }
        """
        )
        res = self.gql(query)
        return res.get("viewer") or {}

    @normalize_exceptions
    def max_cli_version(self) -> Optional[str]:

        if self._max_cli_version is not None:
            return self._max_cli_version

        query_types, server_info_types = self.server_info_introspection()
        cli_version_exists = (
            "serverInfo" in query_types and "cliVersionInfo" in server_info_types
        )
        if not cli_version_exists:
            return None

        _, server_info = self.viewer_server_info()
        self._max_cli_version = server_info.get("cliVersionInfo", {}).get(
            "max_cli_version"
        )
        return self._max_cli_version

    @normalize_exceptions
    def viewer_server_info(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        local_query = """
            latestLocalVersionInfo {
                outOfDate
                latestVersionString
            }
        """
        cli_query = """
            serverInfo {
                cliVersionInfo
                _LOCAL_QUERY_
            }
        """
        query_template = """
        query Viewer{
            viewer {
                id
                entity
                username
                email
                flags
                teams {
                    edges {
                        node {
                            name
                        }
                    }
                }
            }
            _CLI_QUERY_
        }
        """
        query_types, server_info_types = self.server_info_introspection()

        cli_version_exists = (
            "serverInfo" in query_types and "cliVersionInfo" in server_info_types
        )

        local_version_exists = (
            "serverInfo" in query_types
            and "latestLocalVersionInfo" in server_info_types
        )

        cli_query_string = "" if not cli_version_exists else cli_query
        local_query_string = "" if not local_version_exists else local_query

        query_string = query_template.replace("_CLI_QUERY_", cli_query_string).replace(
            "_LOCAL_QUERY_", local_query_string
        )
        query = gql(query_string)
        res = self.gql(query)
        return res.get("viewer") or {}, res.get("serverInfo") or {}

    @normalize_exceptions
    def list_projects(self, entity: Optional[str] = None) -> List[Dict[str, str]]:
        """Lists projects in W&B scoped by entity.

        Arguments:
            entity (str, optional): The entity to scope this project to.

        Returns:
                [{"id","name","description"}]
        """
        query = gql(
            """
        query EntityProjects($entity: String) {
            models(first: 10, entityName: $entity) {
                edges {
                    node {
                        id
                        name
                        description
                    }
                }
            }
        }
        """
        )
        project_list: List[Dict[str, str]] = self._flatten_edges(
            self.gql(
                query, variable_values={"entity": entity or self.settings("entity")}
            )["models"]
        )
        return project_list

    @normalize_exceptions
    def project(self, project: str, entity: Optional[str] = None) -> "_Response":
        """Retrieve project

        Arguments:
            project (str): The project to get details for
            entity (str, optional): The entity to scope this project to.

        Returns:
                [{"id","name","repo","dockerImage","description"}]
        """
        query = gql(
            """
        query ProjectDetails($entity: String, $project: String) {
            model(name: $project, entityName: $entity) {
                id
                name
                repo
                dockerImage
                description
            }
        }
        """
        )
        response: "_Response" = self.gql(
            query, variable_values={"entity": entity, "project": project}
        )["model"]
        return response

    @normalize_exceptions
    def sweep(
        self,
        sweep: str,
        specs: str,
        project: Optional[str] = None,
        entity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieve sweep.

        Arguments:
            sweep (str): The sweep to get details for
            specs (str): history specs
            project (str, optional): The project to scope this sweep to.
            entity (str, optional): The entity to scope this sweep to.

        Returns:
                [{"id","name","repo","dockerImage","description"}]
        """
        query = gql(
            """
        query SweepWithRuns($entity: String, $project: String, $sweep: String!, $specs: [JSONString!]!) {
            project(name: $project, entityName: $entity) {
                sweep(sweepName: $sweep) {
                    id
                    name
                    method
                    state
                    description
                    config
                    createdAt
                    heartbeatAt
                    updatedAt
                    earlyStopJobRunning
                    bestLoss
                    controller
                    scheduler
                    runs {
                        edges {
                            node {
                                name
                                state
                                config
                                exitcode
                                heartbeatAt
                                shouldStop
                                failed
                                stopped
                                running
                                summaryMetrics
                                sampledHistory(specs: $specs)
                            }
                        }
                    }
                }
            }
        }
        """
        )
        entity = entity or self.settings("entity")
        project = project or self.settings("project")
        response = self.gql(
            query,
            variable_values={
                "entity": entity,
                "project": project,
                "sweep": sweep,
                "specs": specs,
            },
        )
        if response["project"] is None or response["project"]["sweep"] is None:
            raise ValueError(f"Sweep {entity}/{project}/{sweep} not found")
        data: Dict[str, Any] = response["project"]["sweep"]
        if data:
            data["runs"] = self._flatten_edges(data["runs"])
        return data

    @normalize_exceptions
    def list_runs(
        self, project: str, entity: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """Lists runs in W&B scoped by project.

        Arguments:
            project (str): The project to scope the runs to
            entity (str, optional): The entity to scope this project to.  Defaults to public models

        Returns:
                [{"id","name","description"}]
        """
        query = gql(
            """
        query ProjectRuns($model: String!, $entity: String) {
            model(name: $model, entityName: $entity) {
                buckets(first: 10) {
                    edges {
                        node {
                            id
                            name
                            displayName
                            description
                        }
                    }
                }
            }
        }
        """
        )
        return self._flatten_edges(
            self.gql(
                query,
                variable_values={
                    "entity": entity or self.settings("entity"),
                    "model": project or self.settings("project"),
                },
            )["model"]["buckets"]
        )

    @normalize_exceptions
    def run_config(
        self, project: str, run: Optional[str] = None, entity: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any], Optional[str], Dict[str, Any]]:
        """Get the relevant configs for a run

        Arguments:
            project (str): The project to download, (can include bucket)
            run (str, optional): The run to download
            entity (str, optional): The entity to scope this project to.
        """
        query = gql(
            """
        query RunConfigs(
            $name: String!,
            $entity: String,
            $run: String!,
            $pattern: String!,
            $includeConfig: Boolean!,
        ) {
            model(name: $name, entityName: $entity) {
                bucket(name: $run) {
                    config @include(if: $includeConfig)
                    commit @include(if: $includeConfig)
                    files(pattern: $pattern) {
                        pageInfo {
                            hasNextPage
                            endCursor
                        }
                        edges {
                            node {
                                name
                                directUrl
                            }
                        }
                    }
                }
            }
        }
        """
        )

        variable_values = {
            "name": project,
            "run": run,
            "entity": entity,
            "includeConfig": True,
        }

        commit: str = ""
        config: Dict[str, Any] = {}
        patch: Optional[str] = None
        metadata: Dict[str, Any] = {}

        # If we use the `names` parameter on the `files` node, then the server
        # will helpfully give us and 'open' file handle to the files that don't
        # exist. This is so that we can upload data to it. However, in this
        # case, we just want to download that file and not upload to it, so
        # let's instead query for the files that do exist using `pattern`
        # (with no wildcards).
        #
        # Unfortunately we're unable to construct a single pattern that matches
        # our 2 files, we would need something like regex for that.
        for filename in [DIFF_FNAME, METADATA_FNAME]:
            variable_values["pattern"] = filename
            response = self.gql(query, variable_values=variable_values)
            if response["model"] is None:
                raise CommError(f"Run {entity}/{project}/{run} not found")
            run_obj: Dict = response["model"]["bucket"]
            # we only need to fetch this config once
            if variable_values["includeConfig"]:
                commit = run_obj["commit"]
                config = json.loads(run_obj["config"] or "{}")
                variable_values["includeConfig"] = False
            if run_obj["files"] is not None:
                for file_edge in run_obj["files"]["edges"]:
                    name = file_edge["node"]["name"]
                    url = file_edge["node"]["directUrl"]
                    res = requests.get(url)
                    res.raise_for_status()
                    if name == METADATA_FNAME:
                        metadata = res.json()
                    elif name == DIFF_FNAME:
                        patch = res.text

        return commit, config, patch, metadata

    @normalize_exceptions
    def run_resume_status(
        self, entity: str, project_name: str, name: str
    ) -> Optional[Dict[str, Any]]:
        """Check if a run exists and get resume information.

        Arguments:
            entity (str): The entity to scope this project to.
            project_name (str): The project to download, (can include bucket)
            name (str): The run to download
        """
        query = gql(
            """
        query RunResumeStatus($project: String, $entity: String, $name: String!) {
            model(name: $project, entityName: $entity) {
                id
                name
                entity {
                    id
                    name
                }

                bucket(name: $name, missingOk: true) {
                    id
                    name
                    summaryMetrics
                    displayName
                    logLineCount
                    historyLineCount
                    eventsLineCount
                    historyTail
                    eventsTail
                    config
                }
            }
        }
        """
        )

        response = self.gql(
            query,
            variable_values={
                "entity": entity,
                "project": project_name,
                "name": name,
            },
        )

        if "model" not in response or "bucket" not in (response["model"] or {}):
            return None

        project = response["model"]
        self.set_setting("project", project_name)
        if "entity" in project:
            self.set_setting("entity", project["entity"]["name"])

        result: Dict[str, Any] = project["bucket"]

        return result

    @normalize_exceptions
    def check_stop_requested(
        self, project_name: str, entity_name: str, run_id: str
    ) -> bool:
        query = gql(
            """
        query RunStoppedStatus($projectName: String, $entityName: String, $runId: String!) {
            project(name:$projectName, entityName:$entityName) {
                run(name:$runId) {
                    stopped
                }
            }
        }
        """
        )

        response = self.gql(
            query,
            variable_values={
                "projectName": project_name,
                "entityName": entity_name,
                "runId": run_id,
            },
        )

        project = response.get("project", None)
        if not project:
            return False
        run = project.get("run", None)
        if not run:
            return False

        status: bool = run["stopped"]
        return status

    def format_project(self, project: str) -> str:
        return re.sub(r"\W+", "-", project.lower()).strip("-_")

    @normalize_exceptions
    def upsert_project(
        self,
        project: str,
        id: Optional[str] = None,
        description: Optional[str] = None,
        entity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new project

        Arguments:
            project (str): The project to create
            description (str, optional): A description of this project
            entity (str, optional): The entity to scope this project to.
        """
        mutation = gql(
            """
        mutation UpsertModel($name: String!, $id: String, $entity: String!, $description: String, $repo: String)  {
            upsertModel(input: { id: $id, name: $name, entityName: $entity, description: $description, repo: $repo }) {
                model {
                    name
                    description
                }
            }
        }
        """
        )
        response = self.gql(
            mutation,
            variable_values={
                "name": self.format_project(project),
                "entity": entity or self.settings("entity"),
                "description": description,
                "id": id,
            },
        )
        # TODO(jhr): Commenting out 'repo' field for cling, add back
        #   'description': description, 'repo': self.git.remote_url, 'id': id})
        result: Dict[str, Any] = response["upsertModel"]["model"]
        return result

    @normalize_exceptions
    def get_project_run_queues(self, entity: str, project: str) -> List[Dict[str, str]]:
        query = gql(
            """
        query ProjectRunQueues($entity: String!, $projectName: String!){
            project(entityName: $entity, name: $projectName) {
                runQueues {
                    id
                    name
                    createdBy
                    access
                }
            }
        }
        """
        )
        variable_values = {
            "projectName": project,
            "entity": entity,
        }

        res = self.gql(query, variable_values)
        if res.get("project") is None:
            raise Exception(
                f"Error fetching run queues for {entity}/{project} "
                "check that you have access to this entity and project"
            )

        project_run_queues: List[Dict[str, str]] = res["project"]["runQueues"]
        return project_run_queues

    @normalize_exceptions
    def create_run_queue(
        self, entity: str, project: str, queue_name: str, access: str
    ) -> Optional[Dict[str, Any]]:
        query = gql(
            """
        mutation createRunQueue($entity: String!, $project: String!, $queueName: String!, $access: RunQueueAccessType!){
            createRunQueue(
                input: {
                    entityName: $entity,
                    projectName: $project,
                    queueName: $queueName,
                    access: $access
                }
            ) {
                success
                queueID
            }
        }
        """
        )
        variable_values = {
            "project": project,
            "entity": entity,
            "access": access,
            "queueName": queue_name,
        }
        result: Optional[Dict[str, Any]] = self.gql(query, variable_values)[
            "createRunQueue"
        ]
        return result

    @normalize_exceptions
    def push_to_run_queue(
        self, queue_name: str, launch_spec: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        # TODO(kdg): add pushToRunQueueByName to avoid this extra query
        entity = launch_spec["entity"]
        project = launch_spec["project"]
        queues_found = self.get_project_run_queues(entity, project)
        matching_queues = [
            q
            for q in queues_found
            if q["name"] == queue_name
            # ensure user has access to queue
            and (
                # TODO: User created queues in the UI have USER access
                q["access"] in ["PROJECT", "USER"]
                or q["createdBy"] == self.default_entity
            )
        ]
        if not matching_queues:
            # in the case of a missing default queue. create it
            if queue_name == "default":
                wandb.termlog(
                    "No default queue existing for {}/{} creating one.".format(
                        entity, project
                    )
                )
                res = self.create_run_queue(
                    launch_spec["entity"],
                    launch_spec["project"],
                    queue_name,
                    access="PROJECT",
                )

                if res is None or res.get("queueID") is None:
                    wandb.termerror(
                        "Unable to create default queue for {}/{}. Run could not be added to a queue".format(
                            entity, project
                        )
                    )
                    return None
                queue_id = res["queueID"]

            else:
                wandb.termwarn(
                    "Unable to push to run queue {}. Queue not found.".format(
                        queue_name
                    )
                )
                return None
        elif len(matching_queues) > 1:
            wandb.termerror(
                "Unable to push to run queue {}. More than one queue found with this name.".format(
                    queue_name
                )
            )
            return None
        else:
            queue_id = matching_queues[0]["id"]

        mutation = gql(
            """
        mutation pushToRunQueue($queueID: ID!, $runSpec: JSONString!) {
            pushToRunQueue(
                input: {
                    queueID: $queueID,
                    runSpec: $runSpec
                }
            ) {
                runQueueItemId
            }
        }
        """
        )
        spec_json = json.dumps(launch_spec)
        response = self.gql(
            mutation, variable_values={"queueID": queue_id, "runSpec": spec_json}
        )
        result: Optional[Dict[str, Any]] = response["pushToRunQueue"]
        return result

    @normalize_exceptions
    def pop_from_run_queue(
        self,
        queue_name: str,
        entity: Optional[str] = None,
        project: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        mutation = gql(
            """
        mutation popFromRunQueue($entity: String!, $project: String!, $queueName: String!, $launchAgentId: ID)  {
            popFromRunQueue(input: {
                entityName: $entity,
                projectName: $project,
                queueName: $queueName,
                launchAgentId: $launchAgentId
            }) {
                runQueueItemId
                runSpec
            }
        }
        """
        )
        response = self.gql(
            mutation,
            variable_values={
                "entity": entity,
                "project": project,
                "queueName": queue_name,
                "launchAgentId": agent_id,
            },
        )
        result: Optional[Dict[str, Any]] = response["popFromRunQueue"]
        return result

    @normalize_exceptions
    def ack_run_queue_item(self, item_id: str, run_id: Optional[str] = None) -> bool:
        mutation = gql(
            """
        mutation ackRunQueueItem($itemId: ID!, $runId: String!)  {
            ackRunQueueItem(input: { runQueueItemId: $itemId, runName: $runId }) {
                success
            }
        }
        """
        )
        response = self.gql(
            mutation, variable_values={"itemId": item_id, "runId": str(run_id)}
        )
        if not response["ackRunQueueItem"]["success"]:
            raise CommError(
                "Error acking run queue item. Item may have already been acknowledged by another process"
            )
        result: bool = response["ackRunQueueItem"]["success"]
        return result

    @normalize_exceptions
    def create_launch_agent(
        self,
        entity: str,
        project: str,
        queues: List[str],
        gorilla_agent_support: bool,
    ) -> dict:
        project_queues = self.get_project_run_queues(entity, project)
        if not project_queues:
            # create default queue if it doesn't already exist
            default = self.create_run_queue(
                entity, project, "default", access="PROJECT"
            )
            if default is None or default.get("queueID") is None:
                raise CommError(
                    "Unable to create default queue for {}/{}. No queues for agent to poll".format(
                        entity, project
                    )
                )
            project_queues = [{"id": default["queueID"], "name": "default"}]
        polling_queue_ids = [
            q["id"] for q in project_queues if q["name"] in queues
        ]  # filter to poll specified queues
        if len(polling_queue_ids) != len(queues):
            raise CommError(
                f"Could not start launch agent: Not all of requested queues ({', '.join(queues)}) found. "
                f"Available queues for this project: {','.join([q['name'] for q in project_queues])}"
            )

        if not gorilla_agent_support:
            # if gorilla doesn't support launch agents, return a client-generated id
            return {
                "success": True,
                "launchAgentId": None,
            }

        hostname = socket.gethostname()
        mutation = gql(
            """
            mutation createLaunchAgent($entity: String!, $project: String!, $queues: [ID!]!, $hostname: String!){
                createLaunchAgent(
                    input: {
                        entityName: $entity,
                        projectName: $project,
                        runQueues: $queues,
                        hostname: $hostname
                    }
                ) {
                    launchAgentId
                }
            }
            """
        )
        variable_values = {
            "entity": entity,
            "project": project,
            "queues": polling_queue_ids,
            "hostname": hostname,
        }
        result: dict = self.gql(mutation, variable_values)["createLaunchAgent"]
        return result

    @normalize_exceptions
    def update_launch_agent_status(
        self,
        agent_id: str,
        status: str,
        gorilla_agent_support: bool,
    ) -> dict:
        if not gorilla_agent_support:
            # if gorilla doesn't support launch agents, this is a no-op
            return {
                "success": True,
            }

        mutation = gql(
            """
            mutation updateLaunchAgent($agentId: ID!, $agentStatus: String){
                updateLaunchAgent(
                    input: {
                        launchAgentId: $agentId
                        agentStatus: $agentStatus
                    }
                ) {
                    success
                }
            }
            """
        )
        variable_values = {
            "agentId": agent_id,
            "agentStatus": status,
        }
        result: dict = self.gql(mutation, variable_values)["updateLaunchAgent"]
        return result

    @normalize_exceptions
    def get_launch_agent(self, agent_id: str, gorilla_agent_support: bool) -> dict:
        if not gorilla_agent_support:
            return {
                "id": None,
                "name": "",
                "stopPolling": False,
            }
        query = gql(
            """
            query LaunchAgent($agentId: ID!) {
                launchAgent(id: $agentId) {
                    id
                    name
                    runQueues
                    hostname
                    agentStatus
                    stopPolling
                    heartbeatAt
                }
            }
            """
        )
        variable_values = {
            "agentId": agent_id,
        }
        result: dict = self.gql(query, variable_values)["launchAgent"]
        return result

    @normalize_exceptions
    def upsert_run(
        self,
        id: Optional[str] = None,
        name: Optional[str] = None,
        project: Optional[str] = None,
        host: Optional[str] = None,
        group: Optional[str] = None,
        tags: Optional[List[str]] = None,
        config: Optional[dict] = None,
        description: Optional[str] = None,
        entity: Optional[str] = None,
        state: Optional[str] = None,
        display_name: Optional[str] = None,
        notes: Optional[str] = None,
        repo: Optional[str] = None,
        job_type: Optional[str] = None,
        program_path: Optional[str] = None,
        commit: Optional[str] = None,
        sweep_name: Optional[str] = None,
        summary_metrics: Optional[str] = None,
        num_retries: Optional[int] = None,
    ) -> Tuple[dict, bool, Optional[List]]:
        """Update a run

        Arguments:
            id (str, optional): The existing run to update
            name (str, optional): The name of the run to create
            group (str, optional): Name of the group this run is a part of
            project (str, optional): The name of the project
            host (str, optional): The name of the host
            tags (list, optional): A list of tags to apply to the run
            config (dict, optional): The latest config params
            description (str, optional): A description of this project
            entity (str, optional): The entity to scope this project to.
            display_name (str, optional): The display name of this project
            notes (str, optional): Notes about this run
            repo (str, optional): Url of the program's repository.
            state (str, optional): State of the program.
            job_type (str, optional): Type of job, e.g 'train'.
            program_path (str, optional): Path to the program.
            commit (str, optional): The Git SHA to associate the run with
            sweep_name (str, optional): The name of the sweep this run is a part of
            summary_metrics (str, optional): The JSON summary metrics
            num_retries (int, optional): Number of retries
        """

        query_string = """
        mutation UpsertBucket(
            $id: String,
            $name: String,
            $project: String,
            $entity: String,
            $groupName: String,
            $description: String,
            $displayName: String,
            $notes: String,
            $commit: String,
            $config: JSONString,
            $host: String,
            $debug: Boolean,
            $program: String,
            $repo: String,
            $jobType: String,
            $state: String,
            $sweep: String,
            $tags: [String!],
            $summaryMetrics: JSONString,
        ) {
            upsertBucket(input: {
                id: $id,
                name: $name,
                groupName: $groupName,
                modelName: $project,
                entityName: $entity,
                description: $description,
                displayName: $displayName,
                notes: $notes,
                config: $config,
                commit: $commit,
                host: $host,
                debug: $debug,
                jobProgram: $program,
                jobRepo: $repo,
                jobType: $jobType,
                state: $state,
                sweep: $sweep,
                tags: $tags,
                summaryMetrics: $summaryMetrics,
            }) {
                bucket {
                    id
                    name
                    displayName
                    description
                    config
                    sweepName
                    project {
                        id
                        name
                        entity {
                            id
                            name
                        }
                    }
                }
                inserted
                _Server_Settings_
            }
        }
        """
        self.server_settings_introspection()

        server_settings_string = (
            """
        serverSettings {
                serverMessages{
                    utfText
                    plainText
                    htmlText
                    messageType
                    messageLevel
                }
         }
        """
            if self._server_settings_type
            else ""
        )

        query_string = query_string.replace("_Server_Settings_", server_settings_string)
        mutation = gql(query_string)
        config_str = json.dumps(config) if config else None
        if not description or description.isspace():
            description = None

        kwargs = {}
        if num_retries is not None:
            kwargs["num_retries"] = num_retries

        variable_values = {
            "id": id,
            "entity": entity or self.settings("entity"),
            "name": name,
            "project": project or util.auto_project_name(program_path),
            "groupName": group,
            "tags": tags,
            "description": description,
            "config": config_str,
            "commit": commit,
            "displayName": display_name,
            "notes": notes,
            "host": None if self.settings().get("anonymous") == "true" else host,
            "debug": env.is_debug(env=self._environ),
            "repo": repo,
            "program": program_path,
            "jobType": job_type,
            "state": state,
            "sweep": sweep_name,
            "summaryMetrics": summary_metrics,
        }

        # retry conflict errors for 2 minutes, default to no_auth_retry
        check_retry_fn = util.make_check_retry_fn(
            check_fn=util.check_retry_conflict_or_gone,
            check_timedelta=datetime.timedelta(minutes=2),
            fallback_retry_fn=util.no_retry_auth,
        )

        response = self.gql(
            mutation,
            variable_values=variable_values,
            check_retry_fn=check_retry_fn,
            **kwargs,
        )

        run_obj: Dict[str, Dict[str, Dict[str, str]]] = response["upsertBucket"][
            "bucket"
        ]
        project_obj: Dict[str, Dict[str, str]] = run_obj.get("project", {})
        if project_obj:
            self.set_setting("project", project_obj["name"])
            entity_obj = project_obj.get("entity", {})
            if entity_obj:
                self.set_setting("entity", entity_obj["name"])

        server_messages = None
        if self._server_settings_type:
            server_messages = (
                response["upsertBucket"]
                .get("serverSettings", {})
                .get("serverMessages", [])
            )
        return (
            response["upsertBucket"]["bucket"],
            response["upsertBucket"]["inserted"],
            server_messages,
        )

    @normalize_exceptions
    def get_run_info(
        self,
        entity: str,
        project: str,
        name: str,
    ) -> dict:
        query = gql(
            """
        query RunInfo($project: String!, $entity: String!, $name: String!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) {
                    runInfo {
                        program
                        args
                        os
                        python
                        colab
                        executable
                        codeSaved
                        cpuCount
                        gpuCount
                        gpu
                        git {
                            remote
                            commit
                        }
                    }
                }
            }
        }
        """
        )
        variable_values = {"project": project, "entity": entity, "name": name}
        res = self.gql(query, variable_values)
        if res.get("project") is None:
            raise CommError(
                "Error fetching run info for {}/{}/{}. Check that this project exists and you have access to this entity and project".format(
                    entity, project, name
                )
            )
        elif res["project"].get("run") is None:
            raise CommError(
                "Error fetching run info for {}/{}/{}. Check that this run id exists".format(
                    entity, project, name
                )
            )
        run_info: dict = res["project"]["run"]["runInfo"]
        return run_info

    @normalize_exceptions
    def get_run_state(self, entity: str, project: str, name: str) -> str:
        query = gql(
            """
        query RunState(
            $project: String!,
            $entity: String!,
            $name: String!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) {
                    state
                }
            }
        }
        """
        )
        variable_values = {
            "project": project,
            "entity": entity,
            "name": name,
        }
        res = self.gql(query, variable_values)
        if res.get("project") is None or res["project"].get("run") is None:
            raise CommError(f"Error fetching run state for {entity}/{project}/{name}.")
        run_state: str = res["project"]["run"]["state"]
        return run_state

    @normalize_exceptions
    def upload_urls(
        self,
        project: str,
        files: Union[List[str], Dict[str, IO]],
        run: Optional[str] = None,
        entity: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Tuple[str, List[str], Dict[str, Dict[str, Any]]]:
        """Generate temporary resumable upload urls

        Arguments:
            project (str): The project to download
            files (list or dict): The filenames to upload
            run (str, optional): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models
            description (str, optional): description

        Returns:
            (bucket_id, file_info)
            bucket_id: id of bucket we uploaded to
            file_info: A dict of filenames and urls, also indicates if this revision already has uploaded files.
                {
                    'weights.h5': { "url": "https://weights.url" },
                    'model.json': { "url": "https://model.json", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' },
                }
        """
        query = gql(
            """
        query RunUploadUrls($name: String!, $files: [String]!, $entity: String, $run: String!, $description: String) {
            model(name: $name, entityName: $entity) {
                bucket(name: $run, desc: $description) {
                    id
                    files(names: $files) {
                        uploadHeaders
                        edges {
                            node {
                                name
                                url(upload: true)
                                updatedAt
                            }
                        }
                    }
                }
            }
        }
        """
        )
        run_id = run or self.current_run_id
        assert run_id, "run must be specified"
        entity = entity or self.settings("entity")
        query_result = self.gql(
            query,
            variable_values={
                "name": project,
                "run": run_id,
                "entity": entity,
                "description": description,
                "files": [file for file in files],
            },
        )

        run_obj = query_result["model"]["bucket"]
        if run_obj:
            result = {
                file["name"]: file for file in self._flatten_edges(run_obj["files"])
            }
            return run_obj["id"], run_obj["files"]["uploadHeaders"], result
        else:
            raise CommError(f"Run does not exist {entity}/{project}/{run_id}.")

    @normalize_exceptions
    def download_urls(
        self,
        project: str,
        run: Optional[str] = None,
        entity: Optional[str] = None,
    ) -> Dict[str, Dict[str, str]]:
        """Generate download urls

        Arguments:
            project (str): The project to download
            run (str): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            A dict of extensions and urls

                {
                    'weights.h5': { "url": "https://weights.url", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' },
                    'model.json': { "url": "https://model.url", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' }
                }
        """
        query = gql(
            """
        query RunDownloadUrls($name: String!, $entity: String, $run: String!)  {
            model(name: $name, entityName: $entity) {
                bucket(name: $run) {
                    files {
                        edges {
                            node {
                                name
                                url
                                md5
                                updatedAt
                            }
                        }
                    }
                }
            }
        }
        """
        )
        run = run or self.current_run_id
        assert run, "run must be specified"
        entity = entity or self.settings("entity")
        query_result = self.gql(
            query,
            variable_values={
                "name": project,
                "run": run,
                "entity": entity,
            },
        )
        if query_result["model"] is None:
            raise CommError(f"Run does not exist {entity}/{project}/{run}.")
        files = self._flatten_edges(query_result["model"]["bucket"]["files"])
        return {file["name"]: file for file in files if file}

    @normalize_exceptions
    def download_url(
        self,
        project: str,
        file_name: str,
        run: Optional[str] = None,
        entity: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Generate download urls

        Arguments:
            project (str): The project to download
            file_name (str): The name of the file to download
            run (str): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            A dict of extensions and urls

                { "url": "https://weights.url", "updatedAt": '2013-04-26T22:22:23.832Z', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==' }

        """
        query = gql(
            """
        query RunDownloadUrl($name: String!, $fileName: String!, $entity: String, $run: String!)  {
            model(name: $name, entityName: $entity) {
                bucket(name: $run) {
                    files(names: [$fileName]) {
                        edges {
                            node {
                                name
                                url
                                md5
                                updatedAt
                            }
                        }
                    }
                }
            }
        }
        """
        )
        run = run or self.current_run_id
        assert run, "run must be specified"
        query_result = self.gql(
            query,
            variable_values={
                "name": project,
                "run": run,
                "fileName": file_name,
                "entity": entity or self.settings("entity"),
            },
        )
        if query_result["model"]:
            files = self._flatten_edges(query_result["model"]["bucket"]["files"])
            return files[0] if len(files) > 0 and files[0].get("updatedAt") else None
        else:
            return None

    @normalize_exceptions
    def download_file(self, url: str) -> Tuple[int, requests.Response]:
        """Initiate a streaming download

        Arguments:
            url (str): The url to download

        Returns:
            A tuple of the content length and the streaming response
        """
        response = requests.get(url, auth=("user", self.api_key), stream=True)
        response.raise_for_status()
        return int(response.headers.get("content-length", 0)), response

    @normalize_exceptions
    def download_write_file(
        self,
        metadata: Dict[str, str],
        out_dir: Optional[str] = None,
    ) -> Tuple[str, Optional[requests.Response]]:
        """Download a file from a run and write it to wandb/

        Arguments:
            metadata (obj): The metadata object for the file to download. Comes from Api.download_urls().
            out_dir (str, optional): The directory to write the file to. Defaults to wandb/

        Returns:
            A tuple of the file's local path and the streaming response. The streaming response is None if the file
            already existed and was up-to-date.
        """
        fileName = metadata["name"]
        path = os.path.join(out_dir or self.settings("wandb_dir"), fileName)
        if self.file_current(fileName, metadata["md5"]):
            return path, None

        size, response = self.download_file(metadata["url"])

        with util.fsync_open(path, "wb") as file:
            for data in response.iter_content(chunk_size=1024):
                file.write(data)

        return path, response

    def upload_file_azure(
        self, url: str, file: Any, extra_headers: Dict[str, str]
    ) -> None:
        """
        Upload a file to azure
        """
        from azure.core.exceptions import AzureError  # type: ignore

        # Configure the client without retries so our existing logic can handle them
        client = self._azure_blob_module.BlobClient.from_blob_url(
            url, retry_policy=self._azure_blob_module.LinearRetry(retry_total=0)
        )
        try:
            if extra_headers.get("Content-MD5") is not None:
                md5: Optional[bytes] = base64.b64decode(extra_headers["Content-MD5"])
            else:
                md5 = None
            content_settings = self._azure_blob_module.ContentSettings(
                content_md5=md5,
                content_type=extra_headers.get("Content-Type"),
            )
            client.upload_blob(
                file,
                max_concurrency=4,
                length=len(file),
                overwrite=True,
                content_settings=content_settings,
            )
        except AzureError as e:
            if hasattr(e, "response"):
                response = requests.models.Response()
                response.status_code = e.response.status_code
                response.headers = e.response.headers
                response.raw = e.response.internal_response
                raise requests.exceptions.RequestException(e.message, response=response)
            else:
                raise requests.exceptions.ConnectionError(e.message)

    def upload_file(
        self,
        url: str,
        file: IO[bytes],
        callback: Optional["ProgressFn"] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Optional[requests.Response]:
        """Uploads a file to W&B with failure resumption

        Arguments:
            url: The url to download
            file: The path to the file you want to upload
            callback: A callback which is passed the number of
            bytes uploaded since the last time it was called, used to report progress
            extra_headers: A dictionary of extra headers to send with the request

        Returns:
            The `requests` library response object
        """
        extra_headers = extra_headers.copy() if extra_headers else {}
        response: Optional[requests.Response] = None
        progress = Progress(file, callback=callback)
        try:
            if "x-ms-blob-type" in extra_headers and self._azure_blob_module:
                self.upload_file_azure(url, progress, extra_headers)
            else:
                if "x-ms-blob-type" in extra_headers:
                    wandb.termwarn(
                        "Azure uploads over 256MB require the azure SDK, install with pip install wandb[azure]",
                        repeat=False,
                    )
                response = requests.put(url, data=progress, headers=extra_headers)
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"upload_file exception {url}: {e}")
            request_headers = e.request.headers if e.request is not None else ""
            logger.error(f"upload_file request headers: {request_headers}")
            response_content = e.response.content if e.response is not None else ""
            logger.error(f"upload_file response body: {response_content}")
            status_code = e.response.status_code if e.response is not None else 0
            # We need to rewind the file for the next retry (the file passed in is seeked to 0)
            progress.rewind()
            # Retry errors from cloud storage or local network issues
            if status_code in (308, 408, 409, 429, 500, 502, 503, 504) or isinstance(
                e, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
            ):
                _e = retry.TransientError(exc=e)
                raise _e.with_traceback(sys.exc_info()[2])
            else:
                util.sentry_reraise(e)

        return response

    @normalize_exceptions
    def register_agent(
        self,
        host: str,
        sweep_id: Optional[str] = None,
        project_name: Optional[str] = None,
        entity: Optional[str] = None,
    ) -> dict:
        """Register a new agent

        Arguments:
            host (str): hostname
            sweep_id (str): sweep id
            project_name: (str): model that contains sweep
            entity: (str): entity that contains sweep
        """
        mutation = gql(
            """
        mutation CreateAgent(
            $host: String!
            $projectName: String,
            $entityName: String,
            $sweep: String!
        ) {
            createAgent(input: {
                host: $host,
                projectName: $projectName,
                entityName: $entityName,
                sweep: $sweep,
            }) {
                agent {
                    id
                }
            }
        }
        """
        )
        if entity is None:
            entity = self.settings("entity")
        if project_name is None:
            project_name = self.settings("project")

        # don't retry on validation or not found errors
        def no_retry_4xx(e: Exception) -> bool:
            if not isinstance(e, requests.HTTPError):
                return True
            if (
                not (e.response.status_code >= 400 and e.response.status_code < 500)
                or e.response.status_code == 429
            ):
                return True
            body = json.loads(e.response.content)
            raise UsageError(body["errors"][0]["message"])

        response = self.gql(
            mutation,
            variable_values={
                "host": host,
                "entityName": entity,
                "projectName": project_name,
                "sweep": sweep_id,
            },
            check_retry_fn=no_retry_4xx,
        )
        result: dict = response["createAgent"]["agent"]
        return result

    def agent_heartbeat(
        self, agent_id: str, metrics: dict, run_states: dict
    ) -> List[str]:
        """Notify server about agent state, receive commands.

        Arguments:
            agent_id (str): agent_id
            metrics (dict): system metrics
            run_states (dict): run_id: state mapping
        Returns:
            List of commands to execute.
        """
        mutation = gql(
            """
        mutation Heartbeat(
            $id: ID!,
            $metrics: JSONString,
            $runState: JSONString
        ) {
            agentHeartbeat(input: {
                id: $id,
                metrics: $metrics,
                runState: $runState
            }) {
                agent {
                    id
                }
                commands
            }
        }
        """
        )

        if agent_id is None:
            raise ValueError("Cannot call heartbeat with an unregistered agent.")

        try:
            response = self.gql(
                mutation,
                variable_values={
                    "id": agent_id,
                    "metrics": json.dumps(metrics),
                    "runState": json.dumps(run_states),
                },
                timeout=60,
            )
        except Exception as e:
            # GQL raises exceptions with stringified python dictionaries :/
            message = ast.literal_eval(e.args[0])["message"]
            logger.error("Error communicating with W&B: %s", message)
            return []
        else:
            result: List[str] = json.loads(response["agentHeartbeat"]["commands"])
            return result

    @staticmethod
    def _validate_config_and_fill_distribution(config: dict) -> dict:
        # verify that parameters are well specified.
        # TODO(dag): deprecate this in favor of jsonschema validation once
        # apiVersion 2 is released and local controller is integrated with
        # wandb/client.

        # avoid modifying the original config dict in
        # case it is reused outside the calling func
        config = deepcopy(config)

        # explicitly cast to dict in case config was passed as a sweepconfig
        # sweepconfig does not serialize cleanly to yaml and breaks graphql,
        # but it is a subclass of dict, so this conversion is clean
        config = dict(config)

        if "parameters" not in config:
            raise ValueError("sweep config must have a parameters section")

        for parameter_name in config["parameters"]:
            parameter = config["parameters"][parameter_name]
            if "min" in parameter and "max" in parameter:
                if "distribution" not in parameter:
                    if isinstance(parameter["min"], int) and isinstance(
                        parameter["max"], int
                    ):
                        parameter["distribution"] = "int_uniform"
                    elif isinstance(parameter["min"], float) and isinstance(
                        parameter["max"], float
                    ):
                        parameter["distribution"] = "uniform"
                    else:
                        raise ValueError(
                            "Parameter %s is ambiguous, please specify bounds as both floats (for a float_"
                            "uniform distribution) or ints (for an int_uniform distribution)."
                            % parameter_name
                        )
        return config

    @normalize_exceptions
    def upsert_sweep(
        self,
        config: dict,
        controller: Optional[str] = None,
        launch_scheduler: Optional[str] = None,
        scheduler: Optional[str] = None,
        obj_id: Optional[str] = None,
        project: Optional[str] = None,
        entity: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Tuple[str, List[str]]:
        """Upsert a sweep object.

        Arguments:
            config (dict): sweep config (will be converted to yaml)
            controller (str): controller to use
            launch_scheduler (str): launch scheduler to use
            scheduler (str): scheduler to use
            obj_id (str): object id
            project (str): project to use
            entity (str): entity to use
            state (str): state
        """
        project_query = """
            project {
                id
                name
                entity {
                    id
                    name
                }
            }
        """
        mutation_str = """
        mutation UpsertSweep(
            $id: ID,
            $config: String,
            $description: String,
            $entityName: String,
            $projectName: String,
            $controller: JSONString,
            $scheduler: JSONString,
            $state: String
        ) {
            upsertSweep(input: {
                id: $id,
                config: $config,
                description: $description,
                entityName: $entityName,
                projectName: $projectName,
                controller: $controller,
                scheduler: $scheduler,
                state: $state
            }) {
                sweep {
                    name
                    _PROJECT_QUERY_
                }
                configValidationWarnings
            }
        }
        """
        # FIXME(jhr): we need protocol versioning to know schema is not supported
        # for now we will just try both new and old query

        # launchScheduler was introduced in core v0.14.0
        mutation_4 = gql(
            mutation_str.replace(
                "$controller: JSONString,",
                "$controller: JSONString,$launchScheduler: JSONString,",
            ).replace(
                "controller: $controller,",
                "controller: $controller,launchScheduler: $launchScheduler,",
            )
        )

        # mutation 3 maps to backend that can support CLI version of at least 0.10.31
        mutation_3 = gql(mutation_str.replace("_PROJECT_QUERY_", project_query))
        mutation_2 = gql(
            mutation_str.replace("_PROJECT_QUERY_", project_query).replace(
                "configValidationWarnings", ""
            )
        )
        mutation_1 = gql(
            mutation_str.replace("_PROJECT_QUERY_", "").replace(
                "configValidationWarnings", ""
            )
        )

        # don't retry on validation errors
        # TODO(jhr): generalize error handling routines
        def no_retry_4xx(e: Exception) -> bool:
            if not isinstance(e, requests.HTTPError):
                return True
            if (
                not (e.response.status_code >= 400 and e.response.status_code < 500)
                or e.response.status_code == 429
            ):
                return True
            body = json.loads(e.response.content)
            raise UsageError(body["errors"][0]["message"])

        # TODO(dag): replace this with a query for protocol versioning
        mutations = [mutation_4, mutation_3, mutation_2, mutation_1]

        config = self._validate_config_and_fill_distribution(config)

        err: Optional[Exception] = None
        for mutation in mutations:
            try:
                response = self.gql(
                    mutation,
                    variable_values={
                        "id": obj_id,
                        "config": yaml.dump(config),
                        "description": config.get("description"),
                        "entityName": entity or self.settings("entity"),
                        "projectName": project or self.settings("project"),
                        "controller": controller,
                        "launchScheduler": launch_scheduler,
                        "scheduler": scheduler,
                    },
                    check_retry_fn=no_retry_4xx,
                )
            except UsageError as e:
                raise e
            except Exception as e:
                # graphql schema exception is generic
                err = e
                continue
            err = None
            break
        if err:
            raise err

        sweep: Dict[str, Dict[str, Dict]] = response["upsertSweep"]["sweep"]
        project_obj: Dict[str, Dict] = sweep.get("project", {})
        if project_obj:
            self.set_setting("project", project_obj["name"])
            entity_obj: dict = project_obj.get("entity", {})
            if entity_obj:
                self.set_setting("entity", entity_obj["name"])

        warnings = response["upsertSweep"].get("configValidationWarnings", [])
        return response["upsertSweep"]["sweep"]["name"], warnings

    @normalize_exceptions
    def create_anonymous_api_key(self) -> str:
        """Creates a new API key belonging to a new anonymous user."""
        mutation = gql(
            """
        mutation CreateAnonymousApiKey {
            createAnonymousEntity(input: {}) {
                apiKey {
                    name
                }
            }
        }
        """
        )

        response = self.gql(mutation, variable_values={})
        key: str = response["createAnonymousEntity"]["apiKey"]["name"]
        return key

    @staticmethod
    def file_current(fname: str, md5: str) -> bool:
        """Checksum a file and compare the md5 with the known md5"""
        return os.path.isfile(fname) and util.md5_file(fname) == md5

    @normalize_exceptions
    def pull(
        self, project: str, run: Optional[str] = None, entity: Optional[str] = None
    ) -> "List[requests.Response]":
        """Download files from W&B

        Arguments:
            project (str): The project to download
            run (str, optional): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models

        Returns:
            The `requests` library response object
        """
        project, run = self.parse_slug(project, run=run)
        urls = self.download_urls(project, run, entity)
        responses = []
        for fileName in urls:
            _, response = self.download_write_file(urls[fileName])
            if response:
                responses.append(response)

        return responses

    def get_project(self) -> str:
        project: str = self.settings("project")
        return project

    @normalize_exceptions
    def push(
        self,
        files: Union[List[str], Dict[str, IO]],
        run: Optional[str] = None,
        entity: Optional[str] = None,
        project: Optional[str] = None,
        description: Optional[str] = None,
        force: bool = True,
        progress: Union[TextIO, bool] = False,
    ) -> "List[Optional[requests.Response]]":
        """Uploads multiple files to W&B

        Arguments:
            files (list or dict): The filenames to upload, when dict the values are open files
            run (str, optional): The run to upload to
            entity (str, optional): The entity to scope this project to.  Defaults to wandb models
            project (str, optional): The name of the project to upload to. Defaults to the one in settings.
            description (str, optional): The description of the changes
            force (bool, optional): Whether to prevent push if git has uncommitted changes
            progress (callable, or stream): If callable, will be called with (chunk_bytes,
                total_bytes) as argument else if True, renders a progress bar to stream.

        Returns:
            A list of `requests.Response` objects
        """
        if project is None:
            project = self.get_project()
        if project is None:
            raise CommError("No project configured.")
        if run is None:
            run = self.current_run_id

        # TODO(adrian): we use a retriable version of self.upload_file() so
        # will never retry self.upload_urls() here. Instead, maybe we should
        # make push itself retriable.
        run_id, upload_headers, result = self.upload_urls(
            project, files, run, entity, description
        )
        extra_headers = {}
        for upload_header in upload_headers:
            key, val = upload_header.split(":", 1)
            extra_headers[key] = val
        responses = []
        for file_name, file_info in result.items():
            file_url = file_info["url"]

            # If the upload URL is relative, fill it in with the base URL,
            # since it's a proxied file store like the on-prem VM.
            if file_url.startswith("/"):
                file_url = f"{self.api_url}{file_url}"

            try:
                # To handle Windows paths
                # TODO: this doesn't handle absolute paths...
                normal_name = os.path.join(*file_name.split("/"))
                open_file = (
                    files[file_name]
                    if isinstance(files, dict)
                    else open(normal_name, "rb")
                )
            except OSError:
                print(f"{file_name} does not exist")
                continue
            if progress is False:
                responses.append(
                    self.upload_file_retry(
                        file_info["url"], open_file, extra_headers=extra_headers
                    )
                )
            else:
                if callable(progress):
                    responses.append(  # type: ignore
                        self.upload_file_retry(
                            file_url, open_file, progress, extra_headers=extra_headers
                        )
                    )
                else:
                    length = os.fstat(open_file.fileno()).st_size
                    with click.progressbar(
                        file=progress,  # type: ignore
                        length=length,
                        label=f"Uploading file: {file_name}",
                        fill_char=click.style("&", fg="green"),
                    ) as bar:
                        responses.append(
                            self.upload_file_retry(
                                file_url,
                                open_file,
                                lambda bites, _: bar.update(bites),
                                extra_headers=extra_headers,
                            )
                        )
            open_file.close()
        return responses

    def link_artifact(
        self,
        client_id: str,
        server_id: str,
        portfolio_name: str,
        entity: str,
        project: str,
        aliases: Sequence[str],
    ) -> Dict[str, Any]:
        template = """
                mutation LinkArtifact(
                    $artifactPortfolioName: String!,
                    $entityName: String!,
                    $projectName: String!,
                    $aliases: [ArtifactAliasInput!],
                    ID_TYPE
                    ) {
                        linkArtifact(input: {
                            artifactPortfolioName: $artifactPortfolioName,
                            entityName: $entityName,
                            projectName: $projectName,
                            aliases: $aliases,
                            ID_VALUE
                        }) {
                            versionIndex
                        }
                    }
            """

        def replace(a: str, b: str) -> None:
            nonlocal template
            template = template.replace(a, b)

        if server_id:
            replace("ID_TYPE", "$artifactID: ID")
            replace("ID_VALUE", "artifactID: $artifactID")
        elif client_id:
            replace("ID_TYPE", "$clientID: ID")
            replace("ID_VALUE", "clientID: $clientID")

        variable_values = {
            "clientID": client_id,
            "artifactID": server_id,
            "artifactPortfolioName": portfolio_name,
            "entityName": entity,
            "projectName": project,
            "aliases": [
                {"alias": alias, "artifactCollectionName": portfolio_name}
                for alias in aliases
            ],
        }

        mutation = gql(template)
        response = self.gql(mutation, variable_values=variable_values)
        link_artifact: Dict[str, Any] = response["linkArtifact"]
        return link_artifact

    def use_artifact(
        self,
        artifact_id: str,
        entity_name: Optional[str] = None,
        project_name: Optional[str] = None,
        run_name: Optional[str] = None,
        use_as: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        query_template = """
        mutation UseArtifact(
            $entityName: String!,
            $projectName: String!,
            $runName: String!,
            $artifactID: ID!,
            _USED_AS_TYPE_
        ) {
            useArtifact(input: {
                entityName: $entityName,
                projectName: $projectName,
                runName: $runName,
                artifactID: $artifactID,
                _USED_AS_VALUE_
            }) {
                artifact {
                    id
                    digest
                    description
                    state
                    createdAt
                    labels
                    metadata
                }
            }
        }
        """

        artifact_types = self.server_use_artifact_input_introspection()
        if "usedAs" in artifact_types:
            query_template = query_template.replace(
                "_USED_AS_TYPE_", "$usedAs: String"
            ).replace("_USED_AS_VALUE_", "usedAs: $usedAs")
        else:
            query_template = query_template.replace("_USED_AS_TYPE_", "").replace(
                "_USED_AS_VALUE_", ""
            )

        query = gql(query_template)

        entity_name = entity_name or self.settings("entity")
        project_name = project_name or self.settings("project")
        run_name = run_name or self.current_run_id

        response = self.gql(
            query,
            variable_values={
                "entityName": entity_name,
                "projectName": project_name,
                "runName": run_name,
                "artifactID": artifact_id,
                "usedAs": use_as,
            },
        )

        if response["useArtifact"]["artifact"]:
            artifact: Dict[str, Any] = response["useArtifact"]["artifact"]
            return artifact
        return None

    def create_artifact_type(
        self,
        artifact_type_name: str,
        entity_name: Optional[str] = None,
        project_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[str]:
        mutation = gql(
            """
        mutation CreateArtifactType(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!,
            $description: String
        ) {
            createArtifactType(input: {
                entityName: $entityName,
                projectName: $projectName,
                name: $artifactTypeName,
                description: $description
            }) {
                artifactType {
                    id
                }
            }
        }
        """
        )
        entity_name = entity_name or self.settings("entity")
        project_name = project_name or self.settings("project")
        response = self.gql(
            mutation,
            variable_values={
                "entityName": entity_name,
                "projectName": project_name,
                "artifactTypeName": artifact_type_name,
                "description": description,
            },
        )
        _id: Optional[str] = response["createArtifactType"]["artifactType"]["id"]
        return _id

    def create_artifact(
        self,
        artifact_type_name: str,
        artifact_collection_name: str,
        digest: str,
        client_id: Optional[str] = None,
        sequence_client_id: Optional[str] = None,
        entity_name: Optional[str] = None,
        project_name: Optional[str] = None,
        run_name: Optional[str] = None,
        description: Optional[str] = None,
        labels: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        aliases: List[Dict[str, str]] = None,
        distributed_id: Optional[str] = None,
        is_user_created: Optional[bool] = False,
        enable_digest_deduplication: Optional[bool] = False,
        history_step: Optional[int] = None,
    ) -> Tuple[Dict, Dict]:
        _, server_info = self.viewer_server_info()
        max_cli_version = server_info.get("cliVersionInfo", {}).get(
            "max_cli_version", None
        )
        can_handle_client_id = max_cli_version is None or parse_version(
            "0.11.0"
        ) <= parse_version(max_cli_version)
        can_handle_dedupe = max_cli_version is None or parse_version(
            "0.12.10"
        ) <= parse_version(max_cli_version)
        can_handle_history = max_cli_version is None or parse_version(
            "0.12.12"
        ) <= parse_version(max_cli_version)

        mutation = gql(
            """
        mutation CreateArtifact(
            $artifactTypeName: String!,
            $artifactCollectionNames: [String!],
            $entityName: String!,
            $projectName: String!,
            $runName: String,
            $description: String,
            $digest: String!,
            $labels: JSONString,
            $aliases: [ArtifactAliasInput!],
            $metadata: JSONString,
            %s
            %s
            %s
            %s
            %s
        ) {
            createArtifact(input: {
                artifactTypeName: $artifactTypeName,
                artifactCollectionNames: $artifactCollectionNames,
                entityName: $entityName,
                projectName: $projectName,
                runName: $runName,
                description: $description,
                digest: $digest,
                digestAlgorithm: MANIFEST_MD5,
                labels: $labels,
                aliases: $aliases,
                metadata: $metadata,
                %s
                %s
                %s
                %s
                %s
            }) {
                artifact {
                    id
                    digest
                    state
                    aliases {
                        artifactCollectionName
                        alias
                    }
                    artifactSequence {
                        id
                        latestArtifact {
                            id
                            versionIndex
                        }
                    }
                }
            }
        }
        """
            %
            # For backwards compatibility with older backends that don't support
            # distributed writers or digest deduplication.
            (
                "$historyStep: Int64!,"
                if can_handle_history and history_step not in [0, None]
                else "",
                "$distributedID: String," if distributed_id else "",
                "$clientID: ID!," if can_handle_client_id else "",
                "$sequenceClientID: ID!," if can_handle_client_id else "",
                "$enableDigestDeduplication: Boolean," if can_handle_dedupe else "",
                # line sep
                "historyStep: $historyStep,"
                if can_handle_history and history_step not in [0, None]
                else "",
                "distributedID: $distributedID," if distributed_id else "",
                "clientID: $clientID," if can_handle_client_id else "",
                "sequenceClientID: $sequenceClientID," if can_handle_client_id else "",
                "enableDigestDeduplication: $enableDigestDeduplication,"
                if can_handle_dedupe
                else "",
            )
        )

        entity_name = entity_name or self.settings("entity")
        project_name = project_name or self.settings("project")
        if not is_user_created:
            run_name = run_name or self.current_run_id
        if aliases is None:
            aliases = []

        response = self.gql(
            mutation,
            variable_values={
                "entityName": entity_name,
                "projectName": project_name,
                "runName": run_name,
                "artifactTypeName": artifact_type_name,
                "artifactCollectionNames": [artifact_collection_name],
                "clientID": client_id,
                "sequenceClientID": sequence_client_id,
                "digest": digest,
                "description": description,
                "aliases": [alias for alias in aliases],
                "labels": json.dumps(util.make_safe_for_json(labels))
                if labels
                else None,
                "metadata": json.dumps(util.make_safe_for_json(metadata))
                if metadata
                else None,
                "distributedID": distributed_id,
                "enableDigestDeduplication": enable_digest_deduplication,
                "historyStep": history_step,
            },
        )
        av = response["createArtifact"]["artifact"]
        # TODO: make this a part of the graph
        av["version"] = "latest"
        for alias in av["aliases"]:
            if alias["artifactCollectionName"] == artifact_collection_name and re.match(
                r"^v\d+$", alias["alias"]
            ):
                av["version"] = alias["alias"]
        latest = response["createArtifact"]["artifact"]["artifactSequence"].get(
            "latestArtifact"
        )
        return av, latest

    def commit_artifact(self, artifact_id: str) -> "_Response":
        mutation = gql(
            """
        mutation CommitArtifact(
            $artifactID: ID!,
        ) {
            commitArtifact(input: {
                artifactID: $artifactID,
            }) {
                artifact {
                    id
                    digest
                }
            }
        }
        """
        )

        # retry conflict errors for 2 minutes, default to no_auth_retry
        check_retry_fn = util.make_check_retry_fn(
            check_fn=util.check_retry_conflict,
            check_timedelta=datetime.timedelta(minutes=2),
            fallback_retry_fn=util.no_retry_auth,
        )

        response: "_Response" = self.gql(  # type: ignore
            mutation,
            variable_values={"artifactID": artifact_id},
            check_retry_fn=check_retry_fn,
        )
        return response

    def create_artifact_manifest(
        self,
        name: str,
        digest: str,
        artifact_id: Optional[str],
        base_artifact_id: Optional[str] = None,
        entity: Optional[str] = None,
        project: Optional[str] = None,
        run: Optional[str] = None,
        include_upload: bool = True,
        type: str = "FULL",
    ) -> Tuple[str, Dict[str, Any]]:
        mutation = gql(
            """
        mutation CreateArtifactManifest(
            $name: String!,
            $digest: String!,
            $artifactID: ID!,
            $baseArtifactID: ID,
            $entityName: String!,
            $projectName: String!,
            $runName: String!,
            $includeUpload: Boolean!,
            %s
        ) {
            createArtifactManifest(input: {
                name: $name,
                digest: $digest,
                artifactID: $artifactID,
                baseArtifactID: $baseArtifactID,
                entityName: $entityName,
                projectName: $projectName,
                runName: $runName,
                %s
            }) {
                artifactManifest {
                    id
                    file {
                        id
                        name
                        displayName
                        uploadUrl @include(if: $includeUpload)
                        uploadHeaders @include(if: $includeUpload)
                    }
                }
            }
        }
        """
            %
            # For backwards compatibility with older backends that don't support
            # patch manifests.
            (
                "$type: ArtifactManifestType = FULL" if type != "FULL" else "",
                "type: $type" if type != "FULL" else "",
            )
        )

        entity_name = entity or self.settings("entity")
        project_name = project or self.settings("project")
        run_name = run or self.current_run_id

        response = self.gql(
            mutation,
            variable_values={
                "name": name,
                "digest": digest,
                "artifactID": artifact_id,
                "baseArtifactID": base_artifact_id,
                "entityName": entity_name,
                "projectName": project_name,
                "runName": run_name,
                "includeUpload": include_upload,
                "type": type,
            },
        )
        return (
            response["createArtifactManifest"]["artifactManifest"]["id"],
            response["createArtifactManifest"]["artifactManifest"]["file"],
        )

    def update_artifact_manifest(
        self,
        artifact_manifest_id: str,
        base_artifact_id: Optional[str] = None,
        digest: Optional[str] = None,
        include_upload: Optional[bool] = True,
    ) -> Tuple[str, Dict[str, Any]]:
        mutation = gql(
            """
        mutation UpdateArtifactManifest(
            $artifactManifestID: ID!,
            $digest: String,
            $baseArtifactID: ID,
            $includeUpload: Boolean!,
        ) {
            updateArtifactManifest(input: {
                artifactManifestID: $artifactManifestID,
                digest: $digest,
                baseArtifactID: $baseArtifactID,
            }) {
                artifactManifest {
                    id
                    file {
                        id
                        name
                        displayName
                        uploadUrl @include(if: $includeUpload)
                        uploadHeaders @include(if: $includeUpload)
                    }
                }
            }
        }
        """
        )

        response = self.gql(
            mutation,
            variable_values={
                "artifactManifestID": artifact_manifest_id,
                "digest": digest,
                "baseArtifactID": base_artifact_id,
                "includeUpload": include_upload,
            },
        )

        return (
            response["updateArtifactManifest"]["artifactManifest"]["id"],
            response["updateArtifactManifest"]["artifactManifest"]["file"],
        )

    def _resolve_client_id(
        self,
        client_id: str,
    ) -> Optional[str]:

        if client_id in self._client_id_mapping:
            return self._client_id_mapping[client_id]

        query = gql(
            """
            query ClientIDMapping($clientID: ID!) {
                clientIDMapping(clientID: $clientID) {
                    serverID
                }
            }
        """
        )
        response = self.gql(
            query,
            variable_values={
                "clientID": client_id,
            },
        )
        server_id = None
        if response is not None:
            client_id_mapping = response.get("clientIDMapping")
            if client_id_mapping is not None:
                server_id = client_id_mapping.get("serverID")
                if server_id is not None:
                    self._client_id_mapping[client_id] = server_id
        return server_id

    @normalize_exceptions
    def create_artifact_files(
        self, artifact_files: Iterable["CreateArtifactFileSpecInput"]
    ) -> Mapping[str, Mapping[str, Any]]:
        mutation = gql(
            """
        mutation CreateArtifactFiles(
            $storageLayout: ArtifactStorageLayout!
            $artifactFiles: [CreateArtifactFileSpecInput!]!
        ) {
            createArtifactFiles(input: {
                artifactFiles: $artifactFiles,
                storageLayout: $storageLayout
            }) {
                files {
                    edges {
                        node {
                            id
                            name
                            displayName
                            uploadUrl
                            uploadHeaders
                            artifact {
                                id
                            }
                        }
                    }
                }
            }
        }
        """
        )

        # TODO: we should use constants here from interface/artifacts.py
        # but probably don't want the dependency. We're going to remove
        # this setting in a future release, so I'm just hard-coding the strings.
        storage_layout = "V2"
        if env.get_use_v1_artifacts():
            storage_layout = "V1"

        response = self.gql(
            mutation,
            variable_values={
                "storageLayout": storage_layout,
                "artifactFiles": [af for af in artifact_files],
            },
        )

        result = {}
        for edge in response["createArtifactFiles"]["files"]["edges"]:
            node = edge["node"]
            result[node["displayName"]] = node
        return result

    @normalize_exceptions
    def notify_scriptable_run_alert(
        self,
        title: str,
        text: str,
        level: Optional[str] = None,
        wait_duration: Optional["Number"] = None,
    ) -> bool:
        mutation = gql(
            """
        mutation NotifyScriptableRunAlert(
            $entityName: String!,
            $projectName: String!,
            $runName: String!,
            $title: String!,
            $text: String!,
            $severity: AlertSeverity = INFO,
            $waitDuration: Duration
        ) {
            notifyScriptableRunAlert(input: {
                entityName: $entityName,
                projectName: $projectName,
                runName: $runName,
                title: $title,
                text: $text,
                severity: $severity,
                waitDuration: $waitDuration
            }) {
               success
            }
        }
        """
        )

        response = self.gql(
            mutation,
            variable_values={
                "entityName": self.settings("entity"),
                "projectName": self.settings("project"),
                "runName": self.current_run_id,
                "title": title,
                "text": text,
                "severity": level,
                "waitDuration": wait_duration,
            },
        )
        success: bool = response["notifyScriptableRunAlert"]["success"]
        return success

    def get_sweep_state(
        self, sweep: str, entity: Optional[str] = None, project: Optional[str] = None
    ) -> "SweepState":
        state: "SweepState" = self.sweep(
            sweep=sweep, entity=entity, project=project, specs="{}"
        )["state"]
        return state

    def set_sweep_state(
        self,
        sweep: str,
        state: "SweepState",
        entity: Optional[str] = None,
        project: Optional[str] = None,
    ) -> None:
        assert state in ("RUNNING", "PAUSED", "CANCELED", "FINISHED")
        s = self.sweep(sweep=sweep, entity=entity, project=project, specs="{}")
        curr_state = s["state"].upper()
        if state == "RUNNING" and curr_state in ("CANCELED", "FINISHED"):
            raise Exception("Cannot resume %s sweep." % curr_state.lower())
        elif state == "PAUSED" and curr_state not in ("PAUSED", "RUNNING"):
            raise Exception("Cannot pause %s sweep." % curr_state.lower())
        elif curr_state not in ("RUNNING", "PAUSED"):
            raise Exception("Sweep already %s." % curr_state.lower())
        sweep_id = s["id"]
        mutation = gql(
            """
        mutation UpsertSweep(
            $id: ID,
            $state: String,
            $entityName: String,
            $projectName: String
        ) {
            upsertSweep(input: {
                id: $id,
                state: $state,
                entityName: $entityName,
                projectName: $projectName
            }){
                sweep {
                    name
                }
            }
        }
        """
        )
        self.gql(
            mutation,
            variable_values={
                "id": sweep_id,
                "state": state,
                "entityName": entity or self.settings("entity"),
                "projectName": project or self.settings("project"),
            },
        )

    def stop_sweep(
        self,
        sweep: str,
        entity: Optional[str] = None,
        project: Optional[str] = None,
    ) -> None:
        """
        Finish the sweep to stop running new runs and let currently running runs finish.
        """
        self.set_sweep_state(
            sweep=sweep, state="FINISHED", entity=entity, project=project
        )

    def cancel_sweep(
        self,
        sweep: str,
        entity: Optional[str] = None,
        project: Optional[str] = None,
    ) -> None:
        """
        Cancel the sweep to kill all running runs and stop running new runs.
        """
        self.set_sweep_state(
            sweep=sweep, state="CANCELED", entity=entity, project=project
        )

    def pause_sweep(
        self,
        sweep: str,
        entity: Optional[str] = None,
        project: Optional[str] = None,
    ) -> None:
        """
        Pause the sweep to temporarily stop running new runs.
        """
        self.set_sweep_state(
            sweep=sweep, state="PAUSED", entity=entity, project=project
        )

    def resume_sweep(
        self,
        sweep: str,
        entity: Optional[str] = None,
        project: Optional[str] = None,
    ) -> None:
        """
        Resume the sweep to continue running new runs.
        """
        self.set_sweep_state(
            sweep=sweep, state="RUNNING", entity=entity, project=project
        )

    def _status_request(self, url: str, length: int) -> requests.Response:
        """Ask google how much we've uploaded"""
        return requests.put(
            url=url,
            headers={"Content-Length": "0", "Content-Range": "bytes */%i" % length},
        )

    def _flatten_edges(self, response: "_Response") -> List[Dict]:
        """Return an array from the nested graphql relay structure"""
        return [node["node"] for node in response["edges"]]
