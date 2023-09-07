"""Use the Public API to export or update data that you have saved to W&B.

Before using this API, you'll want to log data from your script — check the
[Quickstart](https://docs.wandb.ai/quickstart) for more details.

You might use the Public API to
 - update metadata or metrics for an experiment after it has been completed,
 - pull down your results as a dataframe for post-hoc analysis in a Jupyter notebook, or
 - check your saved model artifacts for those tagged as `ready-to-deploy`.

For more on using the Public API, check out [our guide](https://docs.wandb.com/guides/track/public-api-guide).
"""
import ast
import datetime
import io
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import urllib
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
)

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

import requests
from wandb_gql import Client, gql
from wandb_gql.client import RetryError

import wandb
from wandb import env, util
from wandb.apis.internal import Api as InternalApi
from wandb.apis.normalize import normalize_exceptions
from wandb.errors import CommError
from wandb.sdk.data_types._dtypes import InvalidType, Type, TypeRegistry
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import (
    LAUNCH_DEFAULT_PROJECT,
    _fetch_git_repo,
    apply_patch,
    convert_jupyter_notebook_to_script,
)
from wandb.sdk.lib import ipython, json_util, retry, runid
from wandb.sdk.lib.gql_request import GraphQLSession
from wandb.sdk.lib.paths import LogicalPath

if TYPE_CHECKING:
    import wandb.apis.reports
    import wandb.apis.reports.util

from wandb.sdk.artifacts.artifact_state import ArtifactState

logger = logging.getLogger(__name__)

# Only retry requests for 20 seconds in the public api
RETRY_TIMEDELTA = datetime.timedelta(seconds=20)
WANDB_INTERNAL_KEYS = {"_wandb", "wandb_version"}
PROJECT_FRAGMENT = """fragment ProjectFragment on Project {
    id
    name
    entityName
    createdAt
    isBenchmark
}"""

RUN_FRAGMENT = """fragment RunFragment on Run {
    id
    tags
    name
    displayName
    sweepName
    state
    config
    group
    jobType
    commit
    readOnly
    createdAt
    heartbeatAt
    description
    notes
    systemMetrics
    summaryMetrics
    historyLineCount
    user {
        name
        username
    }
    historyKeys
}"""

FILE_FRAGMENT = """fragment RunFilesFragment on Run {
    files(names: $fileNames, after: $fileCursor, first: $fileLimit) {
        edges {
            node {
                id
                name
                url(upload: $upload)
                directUrl
                sizeBytes
                mimetype
                updatedAt
                md5
            }
            cursor
        }
        pageInfo {
            endCursor
            hasNextPage
        }
    }
}"""

ARTIFACTS_TYPES_FRAGMENT = """
fragment ArtifactTypesFragment on ArtifactTypeConnection {
    edges {
         node {
             id
             name
             description
             createdAt
         }
         cursor
    }
    pageInfo {
        endCursor
        hasNextPage
    }
}
"""

# TODO, factor out common file fragment
ARTIFACT_FILES_FRAGMENT = """fragment ArtifactFilesFragment on Artifact {
    files(names: $fileNames, after: $fileCursor, first: $fileLimit) {
        edges {
            node {
                id
                name: displayName
                url
                sizeBytes
                storagePath
                mimetype
                updatedAt
                digest
                md5
            }
            cursor
        }
        pageInfo {
            endCursor
            hasNextPage
        }
    }
}"""

SWEEP_FRAGMENT = """fragment SweepFragment on Sweep {
    id
    name
    method
    state
    description
    displayName
    bestLoss
    config
    createdAt
    updatedAt
    runCount
}
"""


class RetryingClient:
    INFO_QUERY = gql(
        """
        query ServerInfo{
            serverInfo {
                cliVersionInfo
                latestLocalVersionInfo {
                    outOfDate
                    latestVersionString
                }
            }
        }
        """
    )

    def __init__(self, client: Client):
        self._server_info = None
        self._client = client

    @property
    def app_url(self):
        return util.app_url(self._client.transport.url.replace("/graphql", "")) + "/"

    @retry.retriable(
        retry_timedelta=RETRY_TIMEDELTA,
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException),
    )
    def execute(self, *args, **kwargs):
        try:
            return self._client.execute(*args, **kwargs)
        except requests.exceptions.ReadTimeout:
            if "timeout" not in kwargs:
                timeout = self._client.transport.default_timeout
                wandb.termwarn(
                    f"A graphql request initiated by the public wandb API timed out (timeout={timeout} sec). "
                    f"Create a new API with an integer timeout larger than {timeout}, e.g., `api = wandb.Api(timeout={timeout + 10})` "
                    f"to increase the graphql timeout."
                )
            raise

    @property
    def server_info(self):
        if self._server_info is None:
            self._server_info = self.execute(self.INFO_QUERY).get("serverInfo")
        return self._server_info

    def version_supported(self, min_version):
        try:
            from packaging.version import Version as parse_version  # noqa: N813
        except ImportError:
            from pkg_resources import parse_version

        return parse_version(min_version) <= parse_version(
            self.server_info["cliVersionInfo"]["max_cli_version"]
        )


class Api:
    """Used for querying the wandb server.

    Examples:
        Most common way to initialize
        >>> wandb.Api()

    Arguments:
        overrides: (dict) You can set `base_url` if you are using a wandb server
            other than https://api.wandb.ai.
            You can also set defaults for `entity`, `project`, and `run`.
    """

    _HTTP_TIMEOUT = env.get_http_timeout(19)
    VIEWER_QUERY = gql(
        """
        query Viewer{
            viewer {
                id
                flags
                entity
                username
                email
                admin
                apiKeys {
                    edges {
                        node {
                            id
                            name
                            description
                        }
                    }
                }
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
    USERS_QUERY = gql(
        """
        query SearchUsers($query: String) {
            users(query: $query) {
                edges {
                    node {
                        id
                        flags
                        entity
                        admin
                        email
                        deletedAt
                        username
                        apiKeys {
                            edges {
                                node {
                                    id
                                    name
                                    description
                                }
                            }
                        }
                        teams {
                            edges {
                                node {
                                    name
                                }
                            }
                        }
                    }
                }
            }
        }
        """
    )

    CREATE_PROJECT = gql(
        """
        mutation upsertModel(
            $description: String
            $entityName: String
            $id: String
            $name: String
            $framework: String
            $access: String
            $views: JSONString
        ) {
            upsertModel(
            input: {
                description: $description
                entityName: $entityName
                id: $id
                name: $name
                framework: $framework
                access: $access
                views: $views
            }
            ) {
            project {
                id
                name
                entityName
                description
                access
                views
            }
            model {
                id
                name
                entityName
                description
                access
                views
            }
            inserted
            }
        }
    """
    )

    def __init__(
        self,
        overrides=None,
        timeout: Optional[int] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.settings = InternalApi().settings()
        _overrides = overrides or {}
        self._api_key = api_key
        if self.api_key is None and _thread_local_api_settings.cookies is None:
            wandb.login(host=_overrides.get("base_url"))
        self.settings.update(_overrides)
        if "username" in _overrides and "entity" not in _overrides:
            wandb.termwarn(
                'Passing "username" to Api is deprecated. please use "entity" instead.'
            )
            self.settings["entity"] = _overrides["username"]
        self.settings["base_url"] = self.settings["base_url"].rstrip("/")

        self._viewer = None
        self._projects = {}
        self._runs = {}
        self._sweeps = {}
        self._reports = {}
        self._default_entity = None
        self._timeout = timeout if timeout is not None else self._HTTP_TIMEOUT
        auth = None
        if not _thread_local_api_settings.cookies:
            auth = ("api", self.api_key)
        self._base_client = Client(
            transport=GraphQLSession(
                headers={
                    "User-Agent": self.user_agent,
                    "Use-Admin-Privileges": "true",
                    **(_thread_local_api_settings.headers or {}),
                },
                use_json=True,
                # this timeout won't apply when the DNS lookup fails. in that case, it will be 60s
                # https://bugs.python.org/issue22889
                timeout=self._timeout,
                auth=auth,
                url="%s/graphql" % self.settings["base_url"],
                cookies=_thread_local_api_settings.cookies,
            )
        )
        self._client = RetryingClient(self._base_client)

    def create_project(self, name: str, entity: str):
        self.client.execute(self.CREATE_PROJECT, {"entityName": entity, "name": name})

    def create_run(self, **kwargs):
        """Create a new run."""
        if kwargs.get("entity") is None:
            kwargs["entity"] = self.default_entity
        return Run.create(self, **kwargs)

    def create_report(
        self,
        project: str,
        entity: str = "",
        title: Optional[str] = "Untitled Report",
        description: Optional[str] = "",
        width: Optional[str] = "readable",
        blocks: Optional["wandb.apis.reports.util.Block"] = None,
    ) -> "wandb.apis.reports.Report":
        if entity == "":
            entity = self.default_entity or ""
        if blocks is None:
            blocks = []
        return wandb.apis.reports.Report(
            project, entity, title, description, width, blocks
        ).save()

    def create_run_queue(
        self,
        name: str,
        type: "RunQueueResourceType",
        access: "RunQueueAccessType",
        entity: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> None:
        """Create a new run queue (launch).

        Arguments:
            name: (str) Name of the queue to create
            type: (str) Type of resource to be used for the queue. One of "local-container", "local-process", "kubernetes", "sagemaker", or "gcp-vertex".
            access: (str) Access level for the queue. Either "project" or "user".
            entity: (str) Optional name of the entity to create the queue. If None, will use the configured or default entity.
            config: (dict) Optional default resource configuration to be used for the queue.

        Returns:
            The newly created `RunQueue`

        Raises:
            ValueError if any of the parameters are invalid
            wandb.Error on wandb API errors
        """
        # TODO(np): Need to check server capabilities for this feature
        # 0. assert params are valid/normalized
        if entity is None:
            entity = self.settings["entity"] or self.default_entity
            if entity is None:
                raise ValueError(
                    "entity must be passed as a parameter, or set in settings"
                )

        if len(name) == 0:
            raise ValueError("name must be non-empty")
        if len(name) > 64:
            raise ValueError("name must be less than 64 characters")

        access = access.upper()
        if access not in ["PROJECT", "USER"]:
            raise ValueError("access must be one of 'project' or 'user'")

        if type not in [
            "local-container",
            "local-process",
            "kubernetes",
            "sagemaker",
            "gcp-vertex",
        ]:
            raise ValueError(
                "resource_type must be one of 'local-container', 'local-process', 'kubernetes', 'sagemaker', or 'gcp-vertex'"
            )

        if config is None:
            config = {}

        # 1. create required default launch project in the entity
        self.create_project(LAUNCH_DEFAULT_PROJECT, entity)

        api = InternalApi(
            default_settings={
                "entity": entity,
                "project": self.project(LAUNCH_DEFAULT_PROJECT),
            },
            retry_timedelta=RETRY_TIMEDELTA,
        )

        # 2. create default resource config, receive config id
        config_json = json.dumps({"resource_args": {type: config}})
        create_config_result = api.create_default_resource_config(
            entity, type, config_json
        )
        if not create_config_result["success"]:
            raise wandb.Error("failed to create default resource config")
        config_id = create_config_result["defaultResourceConfigID"]

        # 3. create run queue
        create_queue_result = api.create_run_queue(
            entity, LAUNCH_DEFAULT_PROJECT, name, access, config_id
        )
        if not create_queue_result["success"]:
            raise wandb.Error("failed to create run queue")

        return RunQueue(self.client, name, entity, access, config_id, config)

    def load_report(self, path: str) -> "wandb.apis.reports.Report":
        """Get report at a given path.

        Arguments:
            path: (str) Path to the target report in the form `entity/project/reports/reportId`.
                You can get this by copy-pasting the URL after your wandb url.  For example:
                `megatruong/report-editing/reports/My-fabulous-report-title--VmlldzoxOTc1Njk0`

        Returns:
            A `BetaReport` object which represents the report at `path`

        Raises:
            wandb.Error if path is invalid
        """
        return wandb.apis.reports.Report.from_url(path)

    def create_user(self, email, admin=False):
        """Create a new user.

        Arguments:
            email: (str) The name of the team
            admin: (bool) Whether this user should be a global instance admin

        Returns:
            A `User` object
        """
        return User.create(self, email, admin)

    def sync_tensorboard(self, root_dir, run_id=None, project=None, entity=None):
        """Sync a local directory containing tfevent files to wandb."""
        from wandb.sync import SyncManager  # TODO: circular import madness

        run_id = run_id or runid.generate_id()
        project = project or self.settings.get("project") or "uncategorized"
        entity = entity or self.default_entity
        # TODO: pipe through log_path to inform the user how to debug
        sm = SyncManager(
            project=project,
            entity=entity,
            run_id=run_id,
            mark_synced=False,
            app_url=self.client.app_url,
            view=False,
            verbose=False,
            sync_tensorboard=True,
        )
        sm.add(root_dir)
        sm.start()
        while not sm.is_done():
            _ = sm.poll()
        return self.run("/".join([entity, project, run_id]))

    @property
    def client(self):
        return self._client

    @property
    def user_agent(self):
        return "W&B Public Client %s" % wandb.__version__

    @property
    def api_key(self):
        # just use thread local api key if it's set
        if _thread_local_api_settings.api_key:
            return _thread_local_api_settings.api_key
        if self._api_key is not None:
            return self._api_key
        auth = requests.utils.get_netrc_auth(self.settings["base_url"])
        key = None
        if auth:
            key = auth[-1]
        # Environment should take precedence
        if os.getenv("WANDB_API_KEY"):
            key = os.environ["WANDB_API_KEY"]
        self._api_key = key  # memoize key
        return key

    @property
    def default_entity(self):
        if self._default_entity is None:
            res = self._client.execute(self.VIEWER_QUERY)
            self._default_entity = (res.get("viewer") or {}).get("entity")
        return self._default_entity

    @property
    def viewer(self):
        if self._viewer is None:
            self._viewer = User(
                self._client, self._client.execute(self.VIEWER_QUERY).get("viewer")
            )
            self._default_entity = self._viewer.entity
        return self._viewer

    def flush(self):
        """Flush the local cache.

        The api object keeps a local cache of runs, so if the state of the run may
        change while executing your script you must clear the local cache with
        `api.flush()` to get the latest values associated with the run.
        """
        self._runs = {}

    def from_path(self, path):
        """Return a run, sweep, project or report from a path.

        Examples:
            ```
            project = api.from_path("my_project")
            team_project = api.from_path("my_team/my_project")
            run = api.from_path("my_team/my_project/runs/id")
            sweep = api.from_path("my_team/my_project/sweeps/id")
            report = api.from_path("my_team/my_project/reports/My-Report-Vm11dsdf")
            ```

        Arguments:
            path: (str) The path to the project, run, sweep or report

        Returns:
            A `Project`, `Run`, `Sweep`, or `BetaReport` instance.

        Raises:
            wandb.Error if path is invalid or the object doesn't exist
        """
        parts = path.strip("/ ").split("/")
        if len(parts) == 1:
            return self.project(path)
        elif len(parts) == 2:
            return self.project(parts[1], parts[0])
        elif len(parts) == 3:
            return self.run(path)
        elif len(parts) == 4:
            if parts[2].startswith("run"):
                return self.run(path)
            elif parts[2].startswith("sweep"):
                return self.sweep(path)
            elif parts[2].startswith("report"):
                if "--" not in parts[-1]:
                    if "-" in parts[-1]:
                        raise wandb.Error(
                            "Invalid report path, should be team/project/reports/Name--XXXX"
                        )
                    else:
                        parts[-1] = "--" + parts[-1]
                name, id = parts[-1].split("--")
                return BetaReport(
                    self.client,
                    {
                        "display_name": urllib.parse.unquote(name.replace("-", " ")),
                        "id": id,
                        "spec": "{}",
                    },
                    parts[0],
                    parts[1],
                )
        raise wandb.Error(
            "Invalid path, should be TEAM/PROJECT/TYPE/ID where TYPE is runs, sweeps, or reports"
        )

    def _parse_project_path(self, path):
        """Return project and entity for project specified by path."""
        project = self.settings["project"]
        entity = self.settings["entity"] or self.default_entity
        if path is None:
            return entity, project
        parts = path.split("/", 1)
        if len(parts) == 1:
            return entity, path
        return parts

    def _parse_path(self, path):
        """Parse url, filepath, or docker paths.

        Allows paths in the following formats:
        - url: entity/project/runs/id
        - path: entity/project/id
        - docker: entity/project:id

        Entity is optional and will fall back to the current logged-in user.
        """
        project = self.settings["project"]
        entity = self.settings["entity"] or self.default_entity
        parts = (
            path.replace("/runs/", "/").replace("/sweeps/", "/").strip("/ ").split("/")
        )
        if ":" in parts[-1]:
            id = parts[-1].split(":")[-1]
            parts[-1] = parts[-1].split(":")[0]
        elif parts[-1]:
            id = parts[-1]
        if len(parts) > 1:
            project = parts[1]
            if entity and id == project:
                project = parts[0]
            else:
                entity = parts[0]
            if len(parts) == 3:
                entity = parts[0]
        else:
            project = parts[0]
        return entity, project, id

    def _parse_artifact_path(self, path):
        """Return project, entity and artifact name for project specified by path."""
        project = self.settings["project"] or "uncategorized"
        entity = self.settings["entity"] or self.default_entity
        if path is None:
            return entity, project
        parts = path.split("/")
        if len(parts) > 3:
            raise ValueError("Invalid artifact path: %s" % path)
        elif len(parts) == 1:
            return entity, project, path
        elif len(parts) == 2:
            return entity, parts[0], parts[1]
        return parts

    def projects(self, entity=None, per_page=200):
        """Get projects for a given entity.

        Arguments:
            entity: (str) Name of the entity requested.  If None, will fall back to
                default entity passed to `Api`.  If no default entity, will raise a `ValueError`.
            per_page: (int) Sets the page size for query pagination.  None will use the default size.
                Usually there is no reason to change this.

        Returns:
            A `Projects` object which is an iterable collection of `Project` objects.

        """
        if entity is None:
            entity = self.settings["entity"] or self.default_entity
            if entity is None:
                raise ValueError(
                    "entity must be passed as a parameter, or set in settings"
                )
        if entity not in self._projects:
            self._projects[entity] = Projects(self.client, entity, per_page=per_page)
        return self._projects[entity]

    def project(self, name, entity=None):
        if entity is None:
            entity = self.settings["entity"] or self.default_entity
        return Project(self.client, entity, name, {})

    def reports(self, path="", name=None, per_page=50):
        """Get reports for a given project path.

        WARNING: This api is in beta and will likely change in a future release

        Arguments:
            path: (str) path to project the report resides in, should be in the form: "entity/project"
            name: (str) optional name of the report requested.
            per_page: (int) Sets the page size for query pagination.  None will use the default size.
                Usually there is no reason to change this.

        Returns:
            A `Reports` object which is an iterable collection of `BetaReport` objects.
        """
        entity, project, _ = self._parse_path(path + "/fake_run")

        if name:
            name = urllib.parse.unquote(name)
            key = "/".join([entity, project, str(name)])
        else:
            key = "/".join([entity, project])

        if key not in self._reports:
            self._reports[key] = Reports(
                self.client,
                Project(self.client, entity, project, {}),
                name=name,
                per_page=per_page,
            )
        return self._reports[key]

    def create_team(self, team, admin_username=None):
        """Create a new team.

        Arguments:
            team: (str) The name of the team
            admin_username: (str) optional username of the admin user of the team, defaults to the current user.

        Returns:
            A `Team` object
        """
        return Team.create(self, team, admin_username)

    def team(self, team):
        return Team(self.client, team)

    def user(self, username_or_email):
        """Return a user from a username or email address.

        Note: This function only works for Local Admins, if you are trying to get your own user object, please use `api.viewer`.

        Arguments:
            username_or_email: (str) The username or email address of the user

        Returns:
            A `User` object or None if a user couldn't be found
        """
        res = self._client.execute(self.USERS_QUERY, {"query": username_or_email})
        if len(res["users"]["edges"]) == 0:
            return None
        elif len(res["users"]["edges"]) > 1:
            wandb.termwarn(
                "Found multiple users, returning the first user matching {}".format(
                    username_or_email
                )
            )
        return User(self._client, res["users"]["edges"][0]["node"])

    def users(self, username_or_email):
        """Return all users from a partial username or email address query.

        Note: This function only works for Local Admins, if you are trying to get your own user object, please use `api.viewer`.

        Arguments:
            username_or_email: (str) The prefix or suffix of the user you want to find

        Returns:
            An array of `User` objects
        """
        res = self._client.execute(self.USERS_QUERY, {"query": username_or_email})
        return [User(self._client, edge["node"]) for edge in res["users"]["edges"]]

    def runs(
        self,
        path: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        order: str = "-created_at",
        per_page: int = 50,
        include_sweeps: bool = True,
    ):
        """Return a set of runs from a project that match the filters provided.

        You can filter by `config.*`, `summary_metrics.*`, `tags`, `state`, `entity`, `createdAt`, etc.

        Examples:
            Find runs in my_project where config.experiment_name has been set to "foo"
            ```
            api.runs(path="my_entity/my_project", filters={"config.experiment_name": "foo"})
            ```

            Find runs in my_project where config.experiment_name has been set to "foo" or "bar"
            ```
            api.runs(
                path="my_entity/my_project",
                filters={"$or": [{"config.experiment_name": "foo"}, {"config.experiment_name": "bar"}]}
            )
            ```

            Find runs in my_project where config.experiment_name matches a regex (anchors are not supported)
            ```
            api.runs(
                path="my_entity/my_project",
                filters={"config.experiment_name": {"$regex": "b.*"}}
            )
            ```

            Find runs in my_project where the run name matches a regex (anchors are not supported)
            ```
            api.runs(
                path="my_entity/my_project",
                filters={"display_name": {"$regex": "^foo.*"}}
            )
            ```

            Find runs in my_project sorted by ascending loss
            ```
            api.runs(path="my_entity/my_project", order="+summary_metrics.loss")
            ```

        Arguments:
            path: (str) path to project, should be in the form: "entity/project"
            filters: (dict) queries for specific runs using the MongoDB query language.
                You can filter by run properties such as config.key, summary_metrics.key, state, entity, createdAt, etc.
                For example: {"config.experiment_name": "foo"} would find runs with a config entry
                    of experiment name set to "foo"
                You can compose operations to make more complicated queries,
                    see Reference for the language is at  https://docs.mongodb.com/manual/reference/operator/query
            order: (str) Order can be `created_at`, `heartbeat_at`, `config.*.value`, or `summary_metrics.*`.
                If you prepend order with a + order is ascending.
                If you prepend order with a - order is descending (default).
                The default order is run.created_at from newest to oldest.

        Returns:
            A `Runs` object, which is an iterable collection of `Run` objects.
        """
        entity, project = self._parse_project_path(path)
        filters = filters or {}
        key = (path or "") + str(filters) + str(order)
        if not self._runs.get(key):
            self._runs[key] = Runs(
                self.client,
                entity,
                project,
                filters=filters,
                order=order,
                per_page=per_page,
                include_sweeps=include_sweeps,
            )
        return self._runs[key]

    @normalize_exceptions
    def run(self, path=""):
        """Return a single run by parsing path in the form entity/project/run_id.

        Arguments:
            path: (str) path to run in the form `entity/project/run_id`.
                If `api.entity` is set, this can be in the form `project/run_id`
                and if `api.project` is set this can just be the run_id.

        Returns:
            A `Run` object.
        """
        entity, project, run_id = self._parse_path(path)
        if not self._runs.get(path):
            self._runs[path] = Run(self.client, entity, project, run_id)
        return self._runs[path]

    def queued_run(
        self,
        entity,
        project,
        queue_name,
        run_queue_item_id,
        container_job=False,
        project_queue=None,
    ):
        """Return a single queued run based on the path.

        Parses paths of the form entity/project/queue_id/run_queue_item_id.
        """
        return QueuedRun(
            self.client,
            entity,
            project,
            queue_name,
            run_queue_item_id,
            container_job=container_job,
            project_queue=project_queue,
        )

    def run_queue(
        self,
        entity,
        name,
    ):
        """Return the named `RunQueue` for entity.

        To create a new `RunQueue`, use `wandb.Api().create_run_queue(...)`.
        """
        return RunQueue(
            self.client,
            name,
            entity,
        )

    @normalize_exceptions
    def sweep(self, path=""):
        """Return a sweep by parsing path in the form `entity/project/sweep_id`.

        Arguments:
            path: (str, optional) path to sweep in the form entity/project/sweep_id.  If `api.entity`
                is set, this can be in the form project/sweep_id and if `api.project` is set
                this can just be the sweep_id.

        Returns:
            A `Sweep` object.
        """
        entity, project, sweep_id = self._parse_path(path)
        if not self._sweeps.get(path):
            self._sweeps[path] = Sweep(self.client, entity, project, sweep_id)
        return self._sweeps[path]

    @normalize_exceptions
    def artifact_types(self, project=None):
        entity, project = self._parse_project_path(project)
        return ProjectArtifactTypes(self.client, entity, project)

    @normalize_exceptions
    def artifact_type(self, type_name, project=None):
        entity, project = self._parse_project_path(project)
        return ArtifactType(self.client, entity, project, type_name)

    @normalize_exceptions
    def artifact_versions(self, type_name, name, per_page=50):
        entity, project, collection_name = self._parse_artifact_path(name)
        artifact_type = ArtifactType(self.client, entity, project, type_name)
        return artifact_type.collection(collection_name).versions(per_page=per_page)

    @normalize_exceptions
    def artifact(self, name, type=None):
        """Return a single artifact by parsing path in the form `entity/project/name`.

        Arguments:
            name: (str) An artifact name. May be prefixed with entity/project. Valid names
                can be in the following forms:
                    name:version
                    name:alias
            type: (str, optional) The type of artifact to fetch.

        Returns:
            A `Artifact` object.
        """
        if name is None:
            raise ValueError("You must specify name= to fetch an artifact.")
        entity, project, artifact_name = self._parse_artifact_path(name)
        artifact = wandb.Artifact._from_name(
            entity, project, artifact_name, self.client
        )
        if type is not None and artifact.type != type:
            raise ValueError(
                f"type {type} specified but this artifact is of type {artifact.type}"
            )
        return artifact

    @normalize_exceptions
    def job(self, name, path=None):
        if name is None:
            raise ValueError("You must specify name= to fetch a job.")
        elif name.count("/") != 2 or ":" not in name:
            raise ValueError(
                "Invalid job specification. A job must be of the form: <entity>/<project>/<job-name>:<alias-or-version>"
            )
        return Job(self, name, path)

    @normalize_exceptions
    def list_jobs(self, entity, project):
        if entity is None:
            raise ValueError("Specify an entity when listing jobs")
        if project is None:
            raise ValueError("Specify a project when listing jobs")

        query = gql(
            """
        query ArtifactOfType(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!,
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    artifactCollections {
                        edges {
                            node {
                                artifacts {
                                    edges {
                                        node {
                                            id
                                            state
                                            aliases {
                                                alias
                                            }
                                            artifactSequence {
                                                name
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        )

        try:
            artifact_query = self._client.execute(
                query,
                {
                    "projectName": project,
                    "entityName": entity,
                    "artifactTypeName": "job",
                },
            )

            if not artifact_query or not artifact_query["project"]:
                wandb.termerror(
                    f"Project: '{project}' not found in entity: '{entity}' or access denied."
                )
                return []

            if artifact_query["project"]["artifactType"] is None:
                return []

            artifacts = artifact_query["project"]["artifactType"][
                "artifactCollections"
            ]["edges"]

            return [x["node"]["artifacts"] for x in artifacts]
        except requests.exceptions.HTTPError:
            return False


class Attrs:
    def __init__(self, attrs: MutableMapping[str, Any]):
        self._attrs = attrs

    def snake_to_camel(self, string):
        camel = "".join([i.title() for i in string.split("_")])
        return camel[0].lower() + camel[1:]

    def display(self, height=420, hidden=False) -> bool:
        """Display this object in jupyter."""
        html = self.to_html(height, hidden)
        if html is None:
            wandb.termwarn("This object does not support `.display()`")
            return False
        if ipython.in_jupyter():
            ipython.display_html(html)
            return True
        else:
            wandb.termwarn(".display() only works in jupyter environments")
            return False

    def to_html(self, *args, **kwargs):
        return None

    def __getattr__(self, name):
        key = self.snake_to_camel(name)
        if key == "user":
            raise AttributeError
        if key in self._attrs.keys():
            return self._attrs[key]
        elif name in self._attrs.keys():
            return self._attrs[name]
        else:
            raise AttributeError(f"{repr(self)!r} object has no attribute {name!r}")


class Paginator:
    QUERY = None

    def __init__(
        self,
        client: Client,
        variables: MutableMapping[str, Any],
        per_page: Optional[int] = None,
    ):
        self.client = client
        self.variables = variables
        # We don't allow unbounded paging
        self.per_page = per_page
        if self.per_page is None:
            self.per_page = 50
        self.objects = []
        self.index = -1
        self.last_response = None

    def __iter__(self):
        self.index = -1
        return self

    def __len__(self):
        if self.length is None:
            self._load_page()
        if self.length is None:
            raise ValueError("Object doesn't provide length")
        return self.length

    @property
    def length(self):
        raise NotImplementedError

    @property
    def more(self):
        raise NotImplementedError

    @property
    def cursor(self):
        raise NotImplementedError

    def convert_objects(self):
        raise NotImplementedError

    def update_variables(self):
        self.variables.update({"perPage": self.per_page, "cursor": self.cursor})

    def _load_page(self):
        if not self.more:
            return False
        self.update_variables()
        self.last_response = self.client.execute(
            self.QUERY, variable_values=self.variables
        )
        self.objects.extend(self.convert_objects())
        return True

    def __getitem__(self, index):
        loaded = True
        stop = index.stop if isinstance(index, slice) else index
        while loaded and stop > len(self.objects) - 1:
            loaded = self._load_page()
        return self.objects[index]

    def __next__(self):
        self.index += 1
        if len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
            if len(self.objects) <= self.index:
                raise StopIteration
        return self.objects[self.index]

    next = __next__


class User(Attrs):
    CREATE_USER_MUTATION = gql(
        """
    mutation CreateUserFromAdmin($email: String!, $admin: Boolean) {
        createUser(input: {email: $email, admin: $admin}) {
            user {
                id
                name
                username
                email
                admin
            }
        }
    }
        """
    )

    DELETE_API_KEY_MUTATION = gql(
        """
    mutation DeleteApiKey($id: String!) {
        deleteApiKey(input: {id: $id}) {
            success
        }
    }
        """
    )
    GENERATE_API_KEY_MUTATION = gql(
        """
    mutation GenerateApiKey($description: String) {
        generateApiKey(input: {description: $description}) {
            apiKey {
                id
                name
            }
        }
    }
        """
    )

    def __init__(self, client, attrs):
        super().__init__(attrs)
        self._client = client
        self._user_api = None

    @property
    def user_api(self):
        """An instance of the api using credentials from the user."""
        if self._user_api is None and len(self.api_keys) > 0:
            self._user_api = wandb.Api(api_key=self.api_keys[0])
        return self._user_api

    @classmethod
    def create(cls, api, email, admin=False):
        """Create a new user.

        Arguments:
            api: (`Api`) The api instance to use
            email: (str) The name of the team
            admin: (bool) Whether this user should be a global instance admin

        Returns:
            A `User` object
        """
        res = api.client.execute(
            cls.CREATE_USER_MUTATION,
            {"email": email, "admin": admin},
        )
        return User(api.client, res["createUser"]["user"])

    @property
    def api_keys(self):
        if self._attrs.get("apiKeys") is None:
            return []
        return [k["node"]["name"] for k in self._attrs["apiKeys"]["edges"]]

    @property
    def teams(self):
        if self._attrs.get("teams") is None:
            return []
        return [k["node"]["name"] for k in self._attrs["teams"]["edges"]]

    def delete_api_key(self, api_key):
        """Delete a user's api key.

        Returns:
            Boolean indicating success

        Raises:
            ValueError if the api_key couldn't be found
        """
        idx = self.api_keys.index(api_key)
        try:
            self._client.execute(
                self.DELETE_API_KEY_MUTATION,
                {"id": self._attrs["apiKeys"]["edges"][idx]["node"]["id"]},
            )
        except requests.exceptions.HTTPError:
            return False
        return True

    def generate_api_key(self, description=None):
        """Generate a new api key.

        Returns:
            The new api key, or None on failure
        """
        try:
            # We must make this call using credentials from the original user
            key = self.user_api.client.execute(
                self.GENERATE_API_KEY_MUTATION, {"description": description}
            )["generateApiKey"]["apiKey"]
            self._attrs["apiKeys"]["edges"].append({"node": key})
            return key["name"]
        except (requests.exceptions.HTTPError, AttributeError):
            return None

    def __repr__(self):
        if "email" in self._attrs:
            return f"<User {self._attrs['email']}>"
        elif "username" in self._attrs:
            return f"<User {self._attrs['username']}>"
        elif "id" in self._attrs:
            return f"<User {self._attrs['id']}>"
        elif "name" in self._attrs:
            return f"<User {self._attrs['name']!r}>"
        else:
            return "<User ???>"


class Member(Attrs):
    DELETE_MEMBER_MUTATION = gql(
        """
    mutation DeleteInvite($id: String, $entityName: String) {
        deleteInvite(input: {id: $id, entityName: $entityName}) {
            success
        }
    }
  """
    )

    def __init__(self, client, team, attrs):
        super().__init__(attrs)
        self._client = client
        self.team = team

    def delete(self):
        """Remove a member from a team.

        Returns:
            Boolean indicating success
        """
        try:
            return self._client.execute(
                self.DELETE_MEMBER_MUTATION, {"id": self.id, "entityName": self.team}
            )["deleteInvite"]["success"]
        except requests.exceptions.HTTPError:
            return False

    def __repr__(self):
        return f"<Member {self.name} ({self.account_type})>"


class Team(Attrs):
    CREATE_TEAM_MUTATION = gql(
        """
    mutation CreateTeam($teamName: String!, $teamAdminUserName: String) {
        createTeam(input: {teamName: $teamName, teamAdminUserName: $teamAdminUserName}) {
            entity {
                id
                name
                available
                photoUrl
                limits
            }
        }
    }
    """
    )
    CREATE_INVITE_MUTATION = gql(
        """
    mutation CreateInvite($entityName: String!, $email: String, $username: String, $admin: Boolean) {
        createInvite(input: {entityName: $entityName, email: $email, username: $username, admin: $admin}) {
            invite {
                id
                name
                email
                createdAt
                toUser {
                    name
                }
            }
        }
    }
    """
    )
    TEAM_QUERY = gql(
        """
    query Entity($name: String!) {
        entity(name: $name) {
            id
            name
            available
            photoUrl
            readOnly
            readOnlyAdmin
            isTeam
            privateOnly
            storageBytes
            codeSavingEnabled
            defaultAccess
            isPaid
            members {
                id
                admin
                pending
                email
                username
                name
                photoUrl
                accountType
                apiKey
            }
        }
    }
    """
    )
    CREATE_SERVICE_ACCOUNT_MUTATION = gql(
        """
    mutation CreateServiceAccount($entityName: String!, $description: String!) {
        createServiceAccount(
            input: {description: $description, entityName: $entityName}
        ) {
            user {
                id
            }
        }
    }
    """
    )

    def __init__(self, client, name, attrs=None):
        super().__init__(attrs or {})
        self._client = client
        self.name = name
        self.load()

    @classmethod
    def create(cls, api, team, admin_username=None):
        """Create a new team.

        Arguments:
            api: (`Api`) The api instance to use
            team: (str) The name of the team
            admin_username: (str) optional username of the admin user of the team, defaults to the current user.

        Returns:
            A `Team` object
        """
        try:
            api.client.execute(
                cls.CREATE_TEAM_MUTATION,
                {"teamName": team, "teamAdminUserName": admin_username},
            )
        except requests.exceptions.HTTPError:
            pass
        return Team(api.client, team)

    def invite(self, username_or_email, admin=False):
        """Invite a user to a team.

        Arguments:
            username_or_email: (str) The username or email address of the user you want to invite
            admin: (bool) Whether to make this user a team admin, defaults to False

        Returns:
            True on success, False if user was already invited or didn't exist
        """
        variables = {"entityName": self.name, "admin": admin}
        if "@" in username_or_email:
            variables["email"] = username_or_email
        else:
            variables["username"] = username_or_email
        try:
            self._client.execute(self.CREATE_INVITE_MUTATION, variables)
        except requests.exceptions.HTTPError:
            return False
        return True

    def create_service_account(self, description):
        """Create a service account for the team.

        Arguments:
            description: (str) A description for this service account

        Returns:
            The service account `Member` object, or None on failure
        """
        try:
            self._client.execute(
                self.CREATE_SERVICE_ACCOUNT_MUTATION,
                {"description": description, "entityName": self.name},
            )
            self.load(True)
            return self.members[-1]
        except requests.exceptions.HTTPError:
            return None

    def load(self, force=False):
        if force or not self._attrs:
            response = self._client.execute(self.TEAM_QUERY, {"name": self.name})
            self._attrs = response["entity"]
            self._attrs["members"] = [
                Member(self._client, self.name, member)
                for member in self._attrs["members"]
            ]
        return self._attrs

    def __repr__(self):
        return f"<Team {self.name}>"


class Projects(Paginator):
    """An iterable collection of `Project` objects."""

    QUERY = gql(
        """
        query Projects($entity: String, $cursor: String, $perPage: Int = 50) {
            models(entityName: $entity, after: $cursor, first: $perPage) {
                edges {
                    node {
                        ...ProjectFragment
                    }
                    cursor
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
        %s
        """
        % PROJECT_FRAGMENT
    )

    def __init__(self, client, entity, per_page=50):
        self.client = client
        self.entity = entity
        variables = {
            "entity": self.entity,
        }
        super().__init__(client, variables, per_page)

    @property
    def length(self):
        return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["models"]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["models"]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self):
        return [
            Project(self.client, self.entity, p["node"]["name"], p["node"])
            for p in self.last_response["models"]["edges"]
        ]

    def __repr__(self):
        return f"<Projects {self.entity}>"


class Project(Attrs):
    """A project is a namespace for runs."""

    def __init__(self, client, entity, project, attrs):
        super().__init__(dict(attrs))
        self.client = client
        self.name = project
        self.entity = entity

    @property
    def path(self):
        return [self.entity, self.name]

    @property
    def url(self):
        return self.client.app_url + "/".join(self.path + ["workspace"])

    def to_html(self, height=420, hidden=False):
        """Generate HTML containing an iframe displaying this project."""
        url = self.url + "?jupyter=true"
        style = f"border:none;width:100%;height:{height}px;"
        prefix = ""
        if hidden:
            style += "display:none;"
            prefix = ipython.toggle_button("project")
        return prefix + f"<iframe src={url!r} style={style!r}></iframe>"

    def _repr_html_(self) -> str:
        return self.to_html()

    def __repr__(self):
        return "<Project {}>".format("/".join(self.path))

    @normalize_exceptions
    def artifacts_types(self, per_page=50):
        return ProjectArtifactTypes(self.client, self.entity, self.name)

    @normalize_exceptions
    def sweeps(self):
        query = gql(
            """
            query GetSweeps($project: String!, $entity: String!) {
                project(name: $project, entityName: $entity) {
                    totalSweeps
                    sweeps {
                        edges {
                            node {
                                ...SweepFragment
                            }
                            cursor
                        }
                        pageInfo {
                            endCursor
                            hasNextPage
                        }
                    }
                }
            }
            %s
            """
            % SWEEP_FRAGMENT
        )
        variable_values = {"project": self.name, "entity": self.entity}
        ret = self.client.execute(query, variable_values)
        if ret["project"]["totalSweeps"] < 1:
            return []

        return [
            # match format of existing public sweep apis
            Sweep(
                self.client,
                self.entity,
                self.name,
                e["node"]["name"],
                attrs={
                    "id": e["node"]["id"],
                    "name": e["node"]["name"],
                    "bestLoss": e["node"]["bestLoss"],
                    "config": e["node"]["config"],
                },
            )
            for e in ret["project"]["sweeps"]["edges"]
        ]


class Runs(Paginator):
    """An iterable collection of runs associated with a project and optional filter.

    This is generally used indirectly via the `Api`.runs method.
    """

    QUERY = gql(
        """
        query Runs($project: String!, $entity: String!, $cursor: String, $perPage: Int = 50, $order: String, $filters: JSONString) {
            project(name: $project, entityName: $entity) {
                runCount(filters: $filters)
                readOnly
                runs(filters: $filters, after: $cursor, first: $perPage, order: $order) {
                    edges {
                        node {
                            ...RunFragment
                        }
                        cursor
                    }
                    pageInfo {
                        endCursor
                        hasNextPage
                    }
                }
            }
        }
        %s
        """
        % RUN_FRAGMENT
    )

    def __init__(
        self,
        client: "RetryingClient",
        entity: str,
        project: str,
        filters: Optional[Dict[str, Any]] = None,
        order: Optional[str] = None,
        per_page: int = 50,
        include_sweeps: bool = True,
    ):
        self.entity = entity
        self.project = project
        self.filters = filters or {}
        self.order = order
        self._sweeps = {}
        self._include_sweeps = include_sweeps
        variables = {
            "project": self.project,
            "entity": self.entity,
            "order": self.order,
            "filters": json.dumps(self.filters),
        }
        super().__init__(client, variables, per_page)

    @property
    def length(self):
        if self.last_response:
            return self.last_response["project"]["runCount"]
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["runs"]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["runs"]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self):
        objs = []
        if self.last_response is None or self.last_response.get("project") is None:
            raise ValueError("Could not find project %s" % self.project)
        for run_response in self.last_response["project"]["runs"]["edges"]:
            run = Run(
                self.client,
                self.entity,
                self.project,
                run_response["node"]["name"],
                run_response["node"],
                include_sweeps=self._include_sweeps,
            )
            objs.append(run)

            if self._include_sweeps and run.sweep_name:
                if run.sweep_name in self._sweeps:
                    sweep = self._sweeps[run.sweep_name]
                else:
                    sweep = Sweep.get(
                        self.client,
                        self.entity,
                        self.project,
                        run.sweep_name,
                        withRuns=False,
                    )
                    self._sweeps[run.sweep_name] = sweep

                if sweep is None:
                    continue
                run.sweep = sweep

        return objs

    def __repr__(self):
        return f"<Runs {self.entity}/{self.project}>"


class Run(Attrs):
    """A single run associated with an entity and project.

    Attributes:
        tags ([str]): a list of tags associated with the run
        url (str): the url of this run
        id (str): unique identifier for the run (defaults to eight characters)
        name (str): the name of the run
        state (str): one of: running, finished, crashed, killed, preempting, preempted
        config (dict): a dict of hyperparameters associated with the run
        created_at (str): ISO timestamp when the run was started
        system_metrics (dict): the latest system metrics recorded for the run
        summary (dict): A mutable dict-like property that holds the current summary.
                    Calling update will persist any changes.
        project (str): the project associated with the run
        entity (str): the name of the entity associated with the run
        user (str): the name of the user who created the run
        path (str): Unique identifier [entity]/[project]/[run_id]
        notes (str): Notes about the run
        read_only (boolean): Whether the run is editable
        history_keys (str): Keys of the history metrics that have been logged
            with `wandb.log({key: value})`
        metadata (str): Metadata about the run from wandb-metadata.json
    """

    def __init__(
        self,
        client: "RetryingClient",
        entity: str,
        project: str,
        run_id: str,
        attrs: Optional[Mapping] = None,
        include_sweeps: bool = True,
    ):
        """Initialize a Run object.

        Run is always initialized by calling api.runs() where api is an instance of
        wandb.Api.
        """
        _attrs = attrs or {}
        super().__init__(dict(_attrs))
        self.client = client
        self._entity = entity
        self.project = project
        self._files = {}
        self._base_dir = env.get_dir(tempfile.gettempdir())
        self.id = run_id
        self.sweep = None
        self._include_sweeps = include_sweeps
        self.dir = os.path.join(self._base_dir, *self.path)
        try:
            os.makedirs(self.dir)
        except OSError:
            pass
        self._summary = None
        self._metadata: Optional[Dict[str, Any]] = None
        self._state = _attrs.get("state", "not found")

        self.load(force=not _attrs)

    @property
    def state(self):
        return self._state

    @property
    def entity(self):
        return self._entity

    @property
    def username(self):
        wandb.termwarn("Run.username is deprecated. Please use Run.entity instead.")
        return self._entity

    @property
    def storage_id(self):
        # For compatibility with wandb.Run, which has storage IDs
        # in self.storage_id and names in self.id.

        return self._attrs.get("id")

    @property
    def id(self):
        return self._attrs.get("name")

    @id.setter
    def id(self, new_id):
        attrs = self._attrs
        attrs["name"] = new_id
        return new_id

    @property
    def name(self):
        return self._attrs.get("displayName")

    @name.setter
    def name(self, new_name):
        self._attrs["displayName"] = new_name
        return new_name

    @classmethod
    def create(cls, api, run_id=None, project=None, entity=None):
        """Create a run for the given project."""
        run_id = run_id or runid.generate_id()
        project = project or api.settings.get("project") or "uncategorized"
        mutation = gql(
            """
        mutation UpsertBucket($project: String, $entity: String, $name: String!) {
            upsertBucket(input: {modelName: $project, entityName: $entity, name: $name}) {
                bucket {
                    project {
                        name
                        entity { name }
                    }
                    id
                    name
                }
                inserted
            }
        }
        """
        )
        variables = {"entity": entity, "project": project, "name": run_id}
        res = api.client.execute(mutation, variable_values=variables)
        res = res["upsertBucket"]["bucket"]
        return Run(
            api.client,
            res["project"]["entity"]["name"],
            res["project"]["name"],
            res["name"],
            {
                "id": res["id"],
                "config": "{}",
                "systemMetrics": "{}",
                "summaryMetrics": "{}",
                "tags": [],
                "description": None,
                "notes": None,
                "state": "running",
            },
        )

    def load(self, force=False):
        query = gql(
            """
        query Run($project: String!, $entity: String!, $name: String!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) {
                    ...RunFragment
                }
            }
        }
        %s
        """
            % RUN_FRAGMENT
        )
        if force or not self._attrs:
            response = self._exec(query)
            if (
                response is None
                or response.get("project") is None
                or response["project"].get("run") is None
            ):
                raise ValueError("Could not find run %s" % self)
            self._attrs = response["project"]["run"]
            self._state = self._attrs["state"]

            if self._include_sweeps and self.sweep_name and not self.sweep:
                # There may be a lot of runs. Don't bother pulling them all
                # just for the sake of this one.
                self.sweep = Sweep.get(
                    self.client,
                    self.entity,
                    self.project,
                    self.sweep_name,
                    withRuns=False,
                )

        self._attrs["summaryMetrics"] = (
            json.loads(self._attrs["summaryMetrics"])
            if self._attrs.get("summaryMetrics")
            else {}
        )
        self._attrs["systemMetrics"] = (
            json.loads(self._attrs["systemMetrics"])
            if self._attrs.get("systemMetrics")
            else {}
        )
        if self._attrs.get("user"):
            self.user = User(self.client, self._attrs["user"])
        config_user, config_raw = {}, {}
        for key, value in json.loads(self._attrs.get("config") or "{}").items():
            config = config_raw if key in WANDB_INTERNAL_KEYS else config_user
            if isinstance(value, dict) and "value" in value:
                config[key] = value["value"]
            else:
                config[key] = value
        config_raw.update(config_user)
        self._attrs["config"] = config_user
        self._attrs["rawconfig"] = config_raw
        return self._attrs

    @normalize_exceptions
    def wait_until_finished(self):
        query = gql(
            """
            query RunState($project: String!, $entity: String!, $name: String!) {
                project(name: $project, entityName: $entity) {
                    run(name: $name) {
                        state
                    }
                }
            }
        """
        )
        while True:
            res = self._exec(query)
            state = res["project"]["run"]["state"]
            if state in ["finished", "crashed", "failed"]:
                print(f"Run finished with status: {state}")
                self._attrs["state"] = state
                self._state = state
                return
            time.sleep(5)

    @normalize_exceptions
    def update(self):
        """Persist changes to the run object to the wandb backend."""
        mutation = gql(
            """
        mutation UpsertBucket($id: String!, $description: String, $display_name: String, $notes: String, $tags: [String!], $config: JSONString!, $groupName: String) {
            upsertBucket(input: {id: $id, description: $description, displayName: $display_name, notes: $notes, tags: $tags, config: $config, groupName: $groupName}) {
                bucket {
                    ...RunFragment
                }
            }
        }
        %s
        """
            % RUN_FRAGMENT
        )
        _ = self._exec(
            mutation,
            id=self.storage_id,
            tags=self.tags,
            description=self.description,
            notes=self.notes,
            display_name=self.display_name,
            config=self.json_config,
            groupName=self.group,
        )
        self.summary.update()

    @normalize_exceptions
    def delete(self, delete_artifacts=False):
        """Delete the given run from the wandb backend."""
        mutation = gql(
            """
            mutation DeleteRun(
                $id: ID!,
                {}
            ) {{
                deleteRun(input: {{
                    id: $id,
                    {}
                }}) {{
                    clientMutationId
                }}
            }}
        """.format(
                "$deleteArtifacts: Boolean" if delete_artifacts else "",
                "deleteArtifacts: $deleteArtifacts" if delete_artifacts else "",
            )
        )

        self.client.execute(
            mutation,
            variable_values={
                "id": self.storage_id,
                "deleteArtifacts": delete_artifacts,
            },
        )

    def save(self):
        self.update()

    @property
    def json_config(self):
        config = {}
        for k, v in self.config.items():
            config[k] = {"value": v, "desc": None}
        return json.dumps(config)

    def _exec(self, query, **kwargs):
        """Execute a query against the cloud backend."""
        variables = {"entity": self.entity, "project": self.project, "name": self.id}
        variables.update(kwargs)
        return self.client.execute(query, variable_values=variables)

    def _sampled_history(self, keys, x_axis="_step", samples=500):
        spec = {"keys": [x_axis] + keys, "samples": samples}
        query = gql(
            """
        query RunSampledHistory($project: String!, $entity: String!, $name: String!, $specs: [JSONString!]!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) { sampledHistory(specs: $specs) }
            }
        }
        """
        )

        response = self._exec(query, specs=[json.dumps(spec)])
        # sampledHistory returns one list per spec, we only send one spec
        return response["project"]["run"]["sampledHistory"][0]

    def _full_history(self, samples=500, stream="default"):
        node = "history" if stream == "default" else "events"
        query = gql(
            """
        query RunFullHistory($project: String!, $entity: String!, $name: String!, $samples: Int) {
            project(name: $project, entityName: $entity) {
                run(name: $name) { %s(samples: $samples) }
            }
        }
        """
            % node
        )

        response = self._exec(query, samples=samples)
        return [json.loads(line) for line in response["project"]["run"][node]]

    @normalize_exceptions
    def files(self, names=None, per_page=50):
        """Return a file path for each file named.

        Arguments:
            names (list): names of the requested files, if empty returns all files
            per_page (int): number of results per page.

        Returns:
            A `Files` object, which is an iterator over `File` objects.
        """
        return Files(self.client, self, names or [], per_page)

    @normalize_exceptions
    def file(self, name):
        """Return the path of a file with a given name in the artifact.

        Arguments:
            name (str): name of requested file.

        Returns:
            A `File` matching the name argument.
        """
        return Files(self.client, self, [name])[0]

    @normalize_exceptions
    def upload_file(self, path, root="."):
        """Upload a file.

        Arguments:
            path (str): name of file to upload.
            root (str): the root path to save the file relative to.  i.e.
                If you want to have the file saved in the run as "my_dir/file.txt"
                and you're currently in "my_dir" you would set root to "../".

        Returns:
            A `File` matching the name argument.
        """
        api = InternalApi(
            default_settings={"entity": self.entity, "project": self.project},
            retry_timedelta=RETRY_TIMEDELTA,
        )
        api.set_current_run_id(self.id)
        root = os.path.abspath(root)
        name = os.path.relpath(path, root)
        with open(os.path.join(root, name), "rb") as f:
            api.push({LogicalPath(name): f})
        return Files(self.client, self, [name])[0]

    @normalize_exceptions
    def history(
        self, samples=500, keys=None, x_axis="_step", pandas=True, stream="default"
    ):
        """Return sampled history metrics for a run.

        This is simpler and faster if you are ok with the history records being sampled.

        Arguments:
            samples : (int, optional) The number of samples to return
            pandas : (bool, optional) Return a pandas dataframe
            keys : (list, optional) Only return metrics for specific keys
            x_axis : (str, optional) Use this metric as the xAxis defaults to _step
            stream : (str, optional) "default" for metrics, "system" for machine metrics

        Returns:
            pandas.DataFrame: If pandas=True returns a `pandas.DataFrame` of history
                metrics.
            list of dicts: If pandas=False returns a list of dicts of history metrics.
        """
        if keys is not None and not isinstance(keys, list):
            wandb.termerror("keys must be specified in a list")
            return []
        if keys is not None and len(keys) > 0 and not isinstance(keys[0], str):
            wandb.termerror("keys argument must be a list of strings")
            return []

        if keys and stream != "default":
            wandb.termerror("stream must be default when specifying keys")
            return []
        elif keys:
            lines = self._sampled_history(keys=keys, x_axis=x_axis, samples=samples)
        else:
            lines = self._full_history(samples=samples, stream=stream)
        if pandas:
            pandas = util.get_module("pandas")
            if pandas:
                lines = pandas.DataFrame.from_records(lines)
            else:
                print("Unable to load pandas, call history with pandas=False")
        return lines

    @normalize_exceptions
    def scan_history(self, keys=None, page_size=1000, min_step=None, max_step=None):
        """Returns an iterable collection of all history records for a run.

        Example:
            Export all the loss values for an example run

            ```python
            run = api.run("l2k2/examples-numpy-boston/i0wt6xua")
            history = run.scan_history(keys=["Loss"])
            losses = [row["Loss"] for row in history]
            ```


        Arguments:
            keys ([str], optional): only fetch these keys, and only fetch rows that have all of keys defined.
            page_size (int, optional): size of pages to fetch from the api

        Returns:
            An iterable collection over history records (dict).
        """
        if keys is not None and not isinstance(keys, list):
            wandb.termerror("keys must be specified in a list")
            return []
        if keys is not None and len(keys) > 0 and not isinstance(keys[0], str):
            wandb.termerror("keys argument must be a list of strings")
            return []

        last_step = self.lastHistoryStep
        # set defaults for min/max step
        if min_step is None:
            min_step = 0
        if max_step is None:
            max_step = last_step + 1
        # if the max step is past the actual last step, clamp it down
        if max_step > last_step:
            max_step = last_step + 1
        if keys is None:
            return HistoryScan(
                run=self,
                client=self.client,
                page_size=page_size,
                min_step=min_step,
                max_step=max_step,
            )
        else:
            return SampledHistoryScan(
                run=self,
                client=self.client,
                keys=keys,
                page_size=page_size,
                min_step=min_step,
                max_step=max_step,
            )

    @normalize_exceptions
    def logged_artifacts(self, per_page=100):
        return RunArtifacts(self.client, self, mode="logged", per_page=per_page)

    @normalize_exceptions
    def used_artifacts(self, per_page=100):
        return RunArtifacts(self.client, self, mode="used", per_page=per_page)

    @normalize_exceptions
    def use_artifact(self, artifact, use_as=None):
        """Declare an artifact as an input to a run.

        Arguments:
            artifact (`Artifact`): An artifact returned from
                `wandb.Api().artifact(name)`
            use_as (string, optional): A string identifying
                how the artifact is used in the script. Used
                to easily differentiate artifacts used in a
                run, when using the beta wandb launch
                feature's artifact swapping functionality.

        Returns:
            A `Artifact` object.
        """
        api = InternalApi(
            default_settings={"entity": self.entity, "project": self.project},
            retry_timedelta=RETRY_TIMEDELTA,
        )
        api.set_current_run_id(self.id)

        if isinstance(artifact, wandb.Artifact) and not artifact.is_draft():
            api.use_artifact(artifact.id, use_as=use_as or artifact.name)
            return artifact
        elif isinstance(artifact, wandb.Artifact) and artifact.is_draft():
            raise ValueError(
                "Only existing artifacts are accepted by this api. "
                "Manually create one with `wandb artifacts put`"
            )
        else:
            raise ValueError("You must pass a wandb.Api().artifact() to use_artifact")

    @normalize_exceptions
    def log_artifact(self, artifact, aliases=None):
        """Declare an artifact as output of a run.

        Arguments:
            artifact (`Artifact`): An artifact returned from
                `wandb.Api().artifact(name)`
            aliases (list, optional): Aliases to apply to this artifact
        Returns:
            A `Artifact` object.
        """
        api = InternalApi(
            default_settings={"entity": self.entity, "project": self.project},
            retry_timedelta=RETRY_TIMEDELTA,
        )
        api.set_current_run_id(self.id)

        if isinstance(artifact, wandb.Artifact) and not artifact.is_draft():
            artifact_collection_name = artifact.name.split(":")[0]
            api.create_artifact(
                artifact.type,
                artifact_collection_name,
                artifact.digest,
                aliases=aliases,
            )
            return artifact
        elif isinstance(artifact, wandb.Artifact) and artifact.is_draft():
            raise ValueError(
                "Only existing artifacts are accepted by this api. "
                "Manually create one with `wandb artifacts put`"
            )
        else:
            raise ValueError("You must pass a wandb.Api().artifact() to use_artifact")

    @property
    def summary(self):
        if self._summary is None:
            from wandb.old.summary import HTTPSummary

            # TODO: fix the outdir issue
            self._summary = HTTPSummary(self, self.client, summary=self.summary_metrics)
        return self._summary

    @property
    def path(self):
        return [
            urllib.parse.quote_plus(str(self.entity)),
            urllib.parse.quote_plus(str(self.project)),
            urllib.parse.quote_plus(str(self.id)),
        ]

    @property
    def url(self):
        path = self.path
        path.insert(2, "runs")
        return self.client.app_url + "/".join(path)

    @property
    def metadata(self):
        if self._metadata is None:
            try:
                f = self.file("wandb-metadata.json")
                contents = util.download_file_into_memory(f.url, Api().api_key)
                self._metadata = json_util.loads(contents)
            except:  # noqa: E722
                # file doesn't exist, or can't be downloaded, or can't be parsed
                pass
        return self._metadata

    @property
    def lastHistoryStep(self):  # noqa: N802
        query = gql(
            """
        query RunHistoryKeys($project: String!, $entity: String!, $name: String!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) { historyKeys }
            }
        }
        """
        )
        response = self._exec(query)
        if (
            response is None
            or response.get("project") is None
            or response["project"].get("run") is None
            or response["project"]["run"].get("historyKeys") is None
        ):
            return -1
        history_keys = response["project"]["run"]["historyKeys"]
        return history_keys["lastStep"] if "lastStep" in history_keys else -1

    def to_html(self, height=420, hidden=False):
        """Generate HTML containing an iframe displaying this run."""
        url = self.url + "?jupyter=true"
        style = f"border:none;width:100%;height:{height}px;"
        prefix = ""
        if hidden:
            style += "display:none;"
            prefix = ipython.toggle_button()
        return prefix + f"<iframe src={url!r} style={style!r}></iframe>"

    def _repr_html_(self) -> str:
        return self.to_html()

    def __repr__(self):
        return "<Run {} ({})>".format("/".join(self.path), self.state)


class QueuedRun:
    """A single queued run associated with an entity and project. Call `run = queued_run.wait_until_running()` or `run = queued_run.wait_until_finished()` to access the run."""

    def __init__(
        self,
        client,
        entity,
        project,
        queue_name,
        run_queue_item_id,
        container_job=False,
        project_queue=LAUNCH_DEFAULT_PROJECT,
    ):
        self.client = client
        self._entity = entity
        self._project = project
        self._queue_name = queue_name
        self._run_queue_item_id = run_queue_item_id
        self.sweep = None
        self._run = None
        self.container_job = container_job
        self.project_queue = project_queue

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
        if self.container_job:
            raise LaunchError("Container jobs cannot be waited on")

        while True:
            # sleep here to hide an ugly warning
            time.sleep(2)
            item = self._get_item()
            if item and item["associatedRunId"] is not None:
                try:
                    self._run = Run(
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


class RunQueue:
    def __init__(
        self,
        client: RetryingClient,
        name: str,
        entity: str,
        _access: Optional[RunQueueAccessType] = None,
        _default_resource_config_id: Optional[int] = None,
        _default_resource_config: Optional[dict] = None,
    ) -> None:
        self._name: str = name
        self._client = client
        self._entity = entity
        self._access = _access
        self._default_resource_config_id = _default_resource_config_id
        self._default_resource_config = _default_resource_config
        self._type = None
        self._items = None

    @property
    def name(self):
        return self._name

    @property
    def entity(self):
        return self._entity

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
    def items(self) -> List[QueuedRun]:
        """Up to the first 100 queued runs. Modifying this list will not modify the queue or any enqueued items!"""
        # TODO(np): Add a paginated interface
        if self._items is None:
            self._get_items()
        return self._items

    def __repr__(self):
        return f"<RunQueue {self._entity}/{self._name}>"

    @normalize_exceptions
    def _get_metadata(self):
        query = gql(
            """
            query GetRunQueueMetadata($projectName: String!, $entityName: String!, $runQueue: String!) {
                project(name: $projectName, entityName: $entityName) {
                    runQueue(name: $runQueue) {
                        access
                        defaultResourceConfigID
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
        self._access = res["project"]["runQueue"]["access"]
        self._default_resource_config_id = res["project"]["runQueue"][
            "defaultResourceConfigID"
        ]
        if self._default_resource_config_id is None:
            self._default_resource_config = {}

    @normalize_exceptions
    def _get_default_resource_config(self):
        query = gql(
            """
            query GetDefaultResourceConfig($entityName: String!, $id: ID!) {
                entity(name: $entityName) {
                    defaultResourceConfig(id: $id) {
                        config
                        resource
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
        access: "RunQueueAccessType",
        entity: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> "RunQueue":
        public_api = Api()
        return public_api.create_run_queue(
            name,
            resource,
            access,
            entity,
            config,
        )


class Sweep(Attrs):
    """A set of runs associated with a sweep.

    Examples:
        Instantiate with:
        ```
        api = wandb.Api()
        sweep = api.sweep(path/to/sweep)
        ```

    Attributes:
        runs: (`Runs`) list of runs
        id: (str) sweep id
        project: (str) name of project
        config: (str) dictionary of sweep configuration
        state: (str) the state of the sweep
        expected_run_count: (int) number of expected runs for the sweep
    """

    QUERY = gql(
        """
    query Sweep($project: String, $entity: String, $name: String!) {
        project(name: $project, entityName: $entity) {
            sweep(sweepName: $name) {
                id
                name
                state
                runCountExpected
                bestLoss
                config
            }
        }
    }
    """
    )

    LEGACY_QUERY = gql(
        """
    query Sweep($project: String, $entity: String, $name: String!) {
        project(name: $project, entityName: $entity) {
            sweep(sweepName: $name) {
                id
                name
                state
                bestLoss
                config
            }
        }
    }
    """
    )

    def __init__(self, client, entity, project, sweep_id, attrs=None):
        # TODO: Add agents / flesh this out.
        super().__init__(dict(attrs or {}))
        self.client = client
        self._entity = entity
        self.project = project
        self.id = sweep_id
        self.runs = []

        self.load(force=not attrs)

    @property
    def entity(self):
        return self._entity

    @property
    def username(self):
        wandb.termwarn("Sweep.username is deprecated. please use Sweep.entity instead.")
        return self._entity

    @property
    def config(self):
        return util.load_yaml(self._attrs["config"])

    def load(self, force: bool = False):
        if force or not self._attrs:
            sweep = self.get(self.client, self.entity, self.project, self.id)
            if sweep is None:
                raise ValueError("Could not find sweep %s" % self)
            self._attrs = sweep._attrs
            self.runs = sweep.runs

        return self._attrs

    @property
    def order(self):
        if self._attrs.get("config") and self.config.get("metric"):
            sort_order = self.config["metric"].get("goal", "minimize")
            prefix = "+" if sort_order == "minimize" else "-"
            return QueryGenerator.format_order_key(
                prefix + self.config["metric"]["name"]
            )

    def best_run(self, order=None):
        """Return the best run sorted by the metric defined in config or the order passed in."""
        if order is None:
            order = self.order
        else:
            order = QueryGenerator.format_order_key(order)
        if order is None:
            wandb.termwarn(
                "No order specified and couldn't find metric in sweep config, returning most recent run"
            )
        else:
            wandb.termlog("Sorting runs by %s" % order)
        filters = {"$and": [{"sweep": self.id}]}
        try:
            return Runs(
                self.client,
                self.entity,
                self.project,
                order=order,
                filters=filters,
                per_page=1,
            )[0]
        except IndexError:
            return None

    @property
    def expected_run_count(self) -> Optional[int]:
        """Return the number of expected runs in the sweep or None for infinite runs."""
        return self._attrs.get("runCountExpected")

    @property
    def path(self):
        return [
            urllib.parse.quote_plus(str(self.entity)),
            urllib.parse.quote_plus(str(self.project)),
            urllib.parse.quote_plus(str(self.id)),
        ]

    @property
    def url(self):
        path = self.path
        path.insert(2, "sweeps")
        return self.client.app_url + "/".join(path)

    @property
    def name(self):
        return self.config.get("name") or self.id

    @classmethod
    def get(
        cls,
        client,
        entity=None,
        project=None,
        sid=None,
        order=None,
        query=None,
        **kwargs,
    ):
        """Execute a query against the cloud backend."""
        if query is None:
            query = cls.QUERY

        variables = {
            "entity": entity,
            "project": project,
            "name": sid,
        }
        variables.update(kwargs)

        response = None
        try:
            response = client.execute(query, variable_values=variables)
        except Exception:
            # Don't handle exception, rely on legacy query
            # TODO(gst): Implement updated introspection workaround
            query = cls.LEGACY_QUERY
            response = client.execute(query, variable_values=variables)

        if (
            not response
            or not response.get("project")
            or not response["project"].get("sweep")
        ):
            return None

        sweep_response = response["project"]["sweep"]
        sweep = cls(client, entity, project, sid, attrs=sweep_response)
        sweep.runs = Runs(
            client,
            entity,
            project,
            order=order,
            per_page=10,
            filters={"$and": [{"sweep": sweep.id}]},
        )

        return sweep

    def to_html(self, height=420, hidden=False):
        """Generate HTML containing an iframe displaying this sweep."""
        url = self.url + "?jupyter=true"
        style = f"border:none;width:100%;height:{height}px;"
        prefix = ""
        if hidden:
            style += "display:none;"
            prefix = ipython.toggle_button("sweep")
        return prefix + f"<iframe src={url!r} style={style!r}></iframe>"

    def _repr_html_(self) -> str:
        return self.to_html()

    def __repr__(self):
        return "<Sweep {} ({})>".format(
            "/".join(self.path), self._attrs.get("state", "Unknown State")
        )


class Files(Paginator):
    """An iterable collection of `File` objects."""

    QUERY = gql(
        """
        query RunFiles($project: String!, $entity: String!, $name: String!, $fileCursor: String,
            $fileLimit: Int = 50, $fileNames: [String] = [], $upload: Boolean = false) {
            project(name: $project, entityName: $entity) {
                run(name: $name) {
                    fileCount
                    ...RunFilesFragment
                }
            }
        }
        %s
        """
        % FILE_FRAGMENT
    )

    def __init__(self, client, run, names=None, per_page=50, upload=False):
        self.run = run
        variables = {
            "project": run.project,
            "entity": run.entity,
            "name": run.id,
            "fileNames": names or [],
            "upload": upload,
        }
        super().__init__(client, variables, per_page)

    @property
    def length(self):
        if self.last_response:
            return self.last_response["project"]["run"]["fileCount"]
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["run"]["files"]["pageInfo"][
                "hasNextPage"
            ]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["run"]["files"]["edges"][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update({"fileLimit": self.per_page, "fileCursor": self.cursor})

    def convert_objects(self):
        return [
            File(self.client, r["node"])
            for r in self.last_response["project"]["run"]["files"]["edges"]
        ]

    def __repr__(self):
        return "<Files {} ({})>".format("/".join(self.run.path), len(self))


class File(Attrs):
    """File is a class associated with a file saved by wandb.

    Attributes:
        name (string): filename
        url (string): path to file
        direct_url (string): path to file in the bucket
        md5 (string): md5 of file
        mimetype (string): mimetype of file
        updated_at (string): timestamp of last update
        size (int): size of file in bytes

    """

    def __init__(self, client, attrs):
        self.client = client
        self._attrs = attrs
        super().__init__(dict(attrs))

    @property
    def size(self):
        size_bytes = self._attrs["sizeBytes"]
        if size_bytes is not None:
            return int(size_bytes)
        return 0

    @normalize_exceptions
    @retry.retriable(
        retry_timedelta=RETRY_TIMEDELTA,
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException),
    )
    def download(
        self, root: str = ".", replace: bool = False, exist_ok: bool = False
    ) -> io.TextIOWrapper:
        """Downloads a file previously saved by a run from the wandb server.

        Arguments:
            replace (boolean): If `True`, download will overwrite a local file
                if it exists. Defaults to `False`.
            root (str): Local directory to save the file.  Defaults to ".".
            exist_ok (boolean): If `True`, will not raise ValueError if file already
                exists and will not re-download unless replace=True. Defaults to `False`.

        Raises:
            `ValueError` if file already exists, replace=False and exist_ok=False.
        """
        path = os.path.join(root, self.name)
        if os.path.exists(path) and not replace:
            if exist_ok:
                return open(path)
            else:
                raise ValueError(
                    "File already exists, pass replace=True to overwrite or exist_ok=True to leave it as is and don't error."
                )

        util.download_file_from_url(path, self.url, Api().api_key)
        return open(path)

    @normalize_exceptions
    def delete(self):
        mutation = gql(
            """
        mutation deleteFiles($files: [ID!]!) {
            deleteFiles(input: {
                files: $files
            }) {
                success
            }
        }
        """
        )
        self.client.execute(mutation, variable_values={"files": [self.id]})

    def __repr__(self):
        return "<File {} ({}) {}>".format(
            self.name,
            self.mimetype,
            util.to_human_size(self.size, units=util.POW_2_BYTES),
        )


class Reports(Paginator):
    """Reports is an iterable collection of `BetaReport` objects."""

    QUERY = gql(
        """
        query ProjectViews($project: String!, $entity: String!, $reportCursor: String,
            $reportLimit: Int!, $viewType: String = "runs", $viewName: String) {
            project(name: $project, entityName: $entity) {
                allViews(viewType: $viewType, viewName: $viewName, first:
                    $reportLimit, after: $reportCursor) {
                    edges {
                        node {
                            id
                            name
                            displayName
                            description
                            user {
                                username
                                photoUrl
                            }
                            spec
                            updatedAt
                        }
                        cursor
                    }
                    pageInfo {
                        endCursor
                        hasNextPage
                    }

                }
            }
        }
        """
    )

    def __init__(self, client, project, name=None, entity=None, per_page=50):
        self.project = project
        self.name = name
        variables = {
            "project": project.name,
            "entity": project.entity,
            "viewName": self.name,
        }
        super().__init__(client, variables, per_page)

    @property
    def length(self):
        # TODO: Add the count the backend
        if self.last_response:
            return len(self.objects)
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["allViews"]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["allViews"]["edges"][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update(
            {"reportCursor": self.cursor, "reportLimit": self.per_page}
        )

    def convert_objects(self):
        if self.last_response["project"] is None:
            raise ValueError(
                f"Project {self.variables['project']} does not exist under entity {self.variables['entity']}"
            )
        return [
            BetaReport(
                self.client,
                r["node"],
                entity=self.project.entity,
                project=self.project.name,
            )
            for r in self.last_response["project"]["allViews"]["edges"]
        ]

    def __repr__(self):
        return "<Reports {}>".format("/".join(self.project.path))


class QueryGenerator:
    """QueryGenerator is a helper object to write filters for runs."""

    INDIVIDUAL_OP_TO_MONGO = {
        "!=": "$ne",
        ">": "$gt",
        ">=": "$gte",
        "<": "$lt",
        "<=": "$lte",
        "IN": "$in",
        "NIN": "$nin",
        "REGEX": "$regex",
    }
    MONGO_TO_INDIVIDUAL_OP = {v: k for k, v in INDIVIDUAL_OP_TO_MONGO.items()}

    GROUP_OP_TO_MONGO = {"AND": "$and", "OR": "$or"}
    MONGO_TO_GROUP_OP = {v: k for k, v in GROUP_OP_TO_MONGO.items()}

    def __init__(self):
        pass

    @classmethod
    def format_order_key(cls, key: str):
        if key.startswith("+") or key.startswith("-"):
            direction = key[0]
            key = key[1:]
        else:
            direction = "-"
        parts = key.split(".")
        if len(parts) == 1:
            # Assume the user meant summary_metrics if not a run column
            if parts[0] not in ["createdAt", "updatedAt", "name", "sweep"]:
                return direction + "summary_metrics." + parts[0]
        # Assume summary metrics if prefix isn't known
        elif parts[0] not in ["config", "summary_metrics", "tags"]:
            return direction + ".".join(["summary_metrics"] + parts)
        else:
            return direction + ".".join(parts)

    def _is_group(self, op):
        return op.get("filters") is not None

    def _is_individual(self, op):
        return op.get("key") is not None

    def _to_mongo_op_value(self, op, value):
        if op == "=":
            return value
        else:
            return {self.INDIVIDUAL_OP_TO_MONGO[op]: value}

    def key_to_server_path(self, key):
        if key["section"] == "config":
            return "config." + key["name"]
        elif key["section"] == "summary":
            return "summary_metrics." + key["name"]
        elif key["section"] == "keys_info":
            return "keys_info.keys." + key["name"]
        elif key["section"] == "run":
            return key["name"]
        elif key["section"] == "tags":
            return "tags." + key["name"]
        raise ValueError("Invalid key: %s" % key)

    def server_path_to_key(self, path):
        if path.startswith("config."):
            return {"section": "config", "name": path.split("config.", 1)[1]}
        elif path.startswith("summary_metrics."):
            return {"section": "summary", "name": path.split("summary_metrics.", 1)[1]}
        elif path.startswith("keys_info.keys."):
            return {"section": "keys_info", "name": path.split("keys_info.keys.", 1)[1]}
        elif path.startswith("tags."):
            return {"section": "tags", "name": path.split("tags.", 1)[1]}
        else:
            return {"section": "run", "name": path}

    def keys_to_order(self, keys):
        orders = []
        for key in keys["keys"]:
            order = self.key_to_server_path(key["key"])
            if key.get("ascending"):
                order = "+" + order
            else:
                order = "-" + order
            orders.append(order)
        # return ",".join(orders)
        return orders

    def order_to_keys(self, order):
        keys = []
        for k in order:  # orderstr.split(","):
            name = k[1:]
            if k[0] == "+":
                ascending = True
            elif k[0] == "-":
                ascending = False
            else:
                raise Exception("you must sort by ascending(+) or descending(-)")

            key = {"key": {"section": "run", "name": name}, "ascending": ascending}
            keys.append(key)

        return {"keys": keys}

    def _to_mongo_individual(self, filter):
        if filter["key"]["name"] == "":
            return None

        if filter.get("value") is None and filter["op"] != "=" and filter["op"] != "!=":
            return None

        if filter.get("disabled") is not None and filter["disabled"]:
            return None

        if filter["key"]["section"] == "tags":
            if filter["op"] == "IN":
                return {"tags": {"$in": filter["value"]}}
            if filter["value"] is False:
                return {
                    "$or": [{"tags": None}, {"tags": {"$ne": filter["key"]["name"]}}]
                }
            else:
                return {"tags": filter["key"]["name"]}
        path = self.key_to_server_path(filter["key"])
        if path is None:
            return path
        return {path: self._to_mongo_op_value(filter["op"], filter["value"])}

    def filter_to_mongo(self, filter):
        if self._is_individual(filter):
            return self._to_mongo_individual(filter)
        elif self._is_group(filter):
            return {
                self.GROUP_OP_TO_MONGO[filter["op"]]: [
                    self.filter_to_mongo(f) for f in filter["filters"]
                ]
            }

    def mongo_to_filter(self, filter):
        # Returns {"op": "OR", "filters": [{"op": "AND", "filters": []}]}
        if filter is None:
            return None  # this covers the case where self.filter_to_mongo returns None.

        group_op = None
        for key in filter.keys():
            # if self.MONGO_TO_GROUP_OP[key]:
            if key in self.MONGO_TO_GROUP_OP:
                group_op = key
                break
        if group_op is not None:
            return {
                "op": self.MONGO_TO_GROUP_OP[group_op],
                "filters": [self.mongo_to_filter(f) for f in filter[group_op]],
            }
        else:
            for k, v in filter.items():
                if isinstance(v, dict):
                    # TODO: do we always have one key in this case?
                    op = next(iter(v.keys()))
                    return {
                        "key": self.server_path_to_key(k),
                        "op": self.MONGO_TO_INDIVIDUAL_OP[op],
                        "value": v[op],
                    }
                else:
                    return {"key": self.server_path_to_key(k), "op": "=", "value": v}


class PythonMongoishQueryGenerator:
    SPACER = "----------"
    DECIMAL_SPACER = ";;;"
    FRONTEND_NAME_MAPPING = {
        "ID": "name",
        "Name": "displayName",
        "Tags": "tags",
        "State": "state",
        "CreatedTimestamp": "createdAt",
        "Runtime": "duration",
        "User": "username",
        "Sweep": "sweep",
        "Group": "group",
        "JobType": "jobType",
        "Hostname": "host",
        "UsingArtifact": "inputArtifacts",
        "OutputtingArtifact": "outputArtifacts",
        "Step": "_step",
        "Relative Time (Wall)": "_absolute_runtime",
        "Relative Time (Process)": "_runtime",
        "Wall Time": "_timestamp"
        # "GroupedRuns": "__wb_group_by_all"
    }
    FRONTEND_NAME_MAPPING_REVERSED = {v: k for k, v in FRONTEND_NAME_MAPPING.items()}
    AST_OPERATORS = {
        ast.Lt: "$lt",
        ast.LtE: "$lte",
        ast.Gt: "$gt",
        ast.GtE: "$gte",
        ast.Eq: "=",
        ast.Is: "=",
        ast.NotEq: "$ne",
        ast.IsNot: "$ne",
        ast.In: "$in",
        ast.NotIn: "$nin",
        ast.And: "$and",
        ast.Or: "$or",
        ast.Not: "$not",
    }

    if sys.version_info >= (3, 8):
        AST_FIELDS = {
            ast.Constant: "value",
            ast.Name: "id",
            ast.List: "elts",
            ast.Tuple: "elts",
        }
    else:
        AST_FIELDS = {
            ast.Str: "s",
            ast.Num: "n",
            ast.Name: "id",
            ast.List: "elts",
            ast.Tuple: "elts",
            ast.NameConstant: "value",
        }

    def __init__(self, run_set):
        self.run_set = run_set
        self.panel_metrics_helper = PanelMetricsHelper()

    def _handle_compare(self, node):
        # only left side can be a col
        left = self.front_to_back(self._handle_fields(node.left))
        op = self._handle_ops(node.ops[0])
        right = self._handle_fields(node.comparators[0])

        # Eq has no op for some reason
        if op == "=":
            return {left: right}
        else:
            return {left: {op: right}}

    def _handle_fields(self, node):
        result = getattr(node, self.AST_FIELDS.get(type(node)))
        if isinstance(result, list):
            return [self._handle_fields(node) for node in result]
        elif isinstance(result, str):
            return self._unconvert(result)
        return result

    def _handle_ops(self, node):
        return self.AST_OPERATORS.get(type(node))

    def _replace_numeric_dots(self, s):
        numeric_dots = []
        for i, (left, mid, right) in enumerate(zip(s, s[1:], s[2:]), 1):
            if mid == ".":
                if (
                    left.isdigit()
                    and right.isdigit()  # 1.2
                    or left.isdigit()
                    and right == " "  # 1.
                    or left == " "
                    and right.isdigit()  # .2
                ):
                    numeric_dots.append(i)
        # Edge: Catch number ending in dot at end of string
        if s[-2].isdigit() and s[-1] == ".":
            numeric_dots.append(len(s) - 1)
        numeric_dots = [-1] + numeric_dots + [len(s)]

        substrs = []
        for start, stop in zip(numeric_dots, numeric_dots[1:]):
            substrs.append(s[start + 1 : stop])
            substrs.append(self.DECIMAL_SPACER)
        substrs = substrs[:-1]
        return "".join(substrs)

    def _convert(self, filterstr):
        _conversion = (
            self._replace_numeric_dots(filterstr)  # temporarily sub numeric dots
            .replace(".", self.SPACER)  # Allow dotted fields
            .replace(self.DECIMAL_SPACER, ".")  # add them back
        )
        return "(" + _conversion + ")"

    def _unconvert(self, field_name):
        return field_name.replace(self.SPACER, ".")  # Allow dotted fields

    def python_to_mongo(self, filterstr):
        try:
            tree = ast.parse(self._convert(filterstr), mode="eval")
        except SyntaxError as e:
            raise ValueError(
                "Invalid python comparison expression; form something like `my_col == 123`"
            ) from e

        multiple_filters = hasattr(tree.body, "op")

        if multiple_filters:
            op = self.AST_OPERATORS.get(type(tree.body.op))
            values = [self._handle_compare(v) for v in tree.body.values]
        else:
            op = "$and"
            values = [self._handle_compare(tree.body)]
        return {"$or": [{op: values}]}

    def front_to_back(self, name):
        name, *rest = name.split(".")
        rest = "." + ".".join(rest) if rest else ""

        if name in self.FRONTEND_NAME_MAPPING:
            return self.FRONTEND_NAME_MAPPING[name]
        elif name in self.FRONTEND_NAME_MAPPING_REVERSED:
            return name
        elif name in self.run_set._runs_config:
            return f"config.{name}.value{rest}"
        else:  # assume summary metrics
            return f"summary_metrics.{name}{rest}"

    def back_to_front(self, name):
        if name in self.FRONTEND_NAME_MAPPING_REVERSED:
            return self.FRONTEND_NAME_MAPPING_REVERSED[name]
        elif name in self.FRONTEND_NAME_MAPPING:
            return name
        elif (
            name.startswith("config.") and ".value" in name
        ):  # may be brittle: originally "endswith", but that doesn't work with nested keys...
            # strip is weird sometimes (??)
            return name.replace("config.", "").replace(".value", "")
        elif name.startswith("summary_metrics."):
            return name.replace("summary_metrics.", "")
        wandb.termerror(f"Unknown token: {name}")
        return name

    # These are only used for ParallelCoordinatesPlot because it has weird backend names...
    def pc_front_to_back(self, name):
        name, *rest = name.split(".")
        rest = "." + ".".join(rest) if rest else ""
        if name is None:
            return None
        elif name in self.panel_metrics_helper.FRONTEND_NAME_MAPPING:
            return "summary:" + self.panel_metrics_helper.FRONTEND_NAME_MAPPING[name]
        elif name in self.FRONTEND_NAME_MAPPING:
            return self.FRONTEND_NAME_MAPPING[name]
        elif name in self.FRONTEND_NAME_MAPPING_REVERSED:
            return name
        elif name in self.run_set._runs_config:
            return f"config:{name}.value{rest}"
        else:  # assume summary metrics
            return f"summary:{name}{rest}"

    def pc_back_to_front(self, name):
        if name is None:
            return None
        elif "summary:" in name:
            name = name.replace("summary:", "")
            return self.panel_metrics_helper.FRONTEND_NAME_MAPPING_REVERSED.get(
                name, name
            )
        elif name in self.FRONTEND_NAME_MAPPING_REVERSED:
            return self.FRONTEND_NAME_MAPPING_REVERSED[name]
        elif name in self.FRONTEND_NAME_MAPPING:
            return name
        elif name.startswith("config:") and ".value" in name:
            return name.replace("config:", "").replace(".value", "")
        elif name.startswith("summary_metrics."):
            return name.replace("summary_metrics.", "")
        return name


class PanelMetricsHelper:
    FRONTEND_NAME_MAPPING = {
        "Step": "_step",
        "Relative Time (Wall)": "_absolute_runtime",
        "Relative Time (Process)": "_runtime",
        "Wall Time": "_timestamp",
    }
    FRONTEND_NAME_MAPPING_REVERSED = {v: k for k, v in FRONTEND_NAME_MAPPING.items()}

    RUN_MAPPING = {"Created Timestamp": "createdAt", "Latest Timestamp": "heartbeatAt"}
    RUN_MAPPING_REVERSED = {v: k for k, v in RUN_MAPPING.items()}

    def front_to_back(self, name):
        if name in self.FRONTEND_NAME_MAPPING:
            return self.FRONTEND_NAME_MAPPING[name]
        return name

    def back_to_front(self, name):
        if name in self.FRONTEND_NAME_MAPPING_REVERSED:
            return self.FRONTEND_NAME_MAPPING_REVERSED[name]
        return name

    # ScatterPlot and ParallelCoords have weird conventions
    def special_front_to_back(self, name):
        if name is None:
            return name

        name, *rest = name.split(".")
        rest = "." + ".".join(rest) if rest else ""

        # special case for config
        if name.startswith("c::"):
            name = name[3:]
            return f"config:{name}.value{rest}"

        # special case for summary
        if name.startswith("s::"):
            name = name[3:] + rest
            return f"summary:{name}"

        name = name + rest
        if name in self.RUN_MAPPING:
            return "run:" + self.RUN_MAPPING[name]
        if name in self.FRONTEND_NAME_MAPPING:
            return "summary:" + self.FRONTEND_NAME_MAPPING[name]
        if name == "Index":
            return name
        return "summary:" + name

    def special_back_to_front(self, name):
        if name is not None:
            kind, rest = name.split(":", 1)

            if kind == "config":
                pieces = rest.split(".")
                if len(pieces) <= 1:
                    raise ValueError(f"Invalid name: {name}")
                elif len(pieces) == 2:
                    name = pieces[0]
                elif len(pieces) >= 3:
                    name = pieces[:1] + pieces[2:]
                    name = ".".join(name)
                return f"c::{name}"

            elif kind == "summary":
                name = rest
                return f"s::{name}"

        if name is None:
            return name
        elif "summary:" in name:
            name = name.replace("summary:", "")
            return self.FRONTEND_NAME_MAPPING_REVERSED.get(name, name)
        elif "run:" in name:
            name = name.replace("run:", "")
            return self.RUN_MAPPING_REVERSED[name]
        return name


class BetaReport(Attrs):
    """BetaReport is a class associated with reports created in wandb.

    WARNING: this API will likely change in a future release

    Attributes:
        name (string): report name
        description (string): report description;
        user (User): the user that created the report
        spec (dict): the spec off the report;
        updated_at (string): timestamp of last update
    """

    def __init__(self, client, attrs, entity=None, project=None):
        self.client = client
        self.project = project
        self.entity = entity
        self.query_generator = QueryGenerator()
        super().__init__(dict(attrs))
        self._attrs["spec"] = json.loads(self._attrs["spec"])

    @property
    def sections(self):
        return self.spec["panelGroups"]

    def runs(self, section, per_page=50, only_selected=True):
        run_set_idx = section.get("openRunSet", 0)
        run_set = section["runSets"][run_set_idx]
        order = self.query_generator.key_to_server_path(run_set["sort"]["key"])
        if run_set["sort"].get("ascending"):
            order = "+" + order
        else:
            order = "-" + order
        filters = self.query_generator.filter_to_mongo(run_set["filters"])
        if only_selected:
            # TODO: handle this not always existing
            filters["$or"][0]["$and"].append(
                {"name": {"$in": run_set["selections"]["tree"]}}
            )
        return Runs(
            self.client,
            self.entity,
            self.project,
            filters=filters,
            order=order,
            per_page=per_page,
        )

    @property
    def updated_at(self):
        return self._attrs["updatedAt"]

    @property
    def url(self):
        return self.client.app_url + "/".join(
            [
                self.entity,
                self.project,
                "reports",
                "--".join(
                    [
                        urllib.parse.quote(self.display_name.replace(" ", "-")),
                        self.id.replace("=", ""),
                    ]
                ),
            ]
        )

    def to_html(self, height=1024, hidden=False):
        """Generate HTML containing an iframe displaying this report."""
        url = self.url + "?jupyter=true"
        style = f"border:none;width:100%;height:{height}px;"
        prefix = ""
        if hidden:
            style += "display:none;"
            prefix = ipython.toggle_button("report")
        return prefix + f"<iframe src={url!r} style={style!r}></iframe>"

    def _repr_html_(self) -> str:
        return self.to_html()


class HistoryScan:
    QUERY = gql(
        """
        query HistoryPage($entity: String!, $project: String!, $run: String!, $minStep: Int64!, $maxStep: Int64!, $pageSize: Int!) {
            project(name: $project, entityName: $entity) {
                run(name: $run) {
                    history(minStep: $minStep, maxStep: $maxStep, samples: $pageSize)
                }
            }
        }
        """
    )

    def __init__(self, client, run, min_step, max_step, page_size=1000):
        self.client = client
        self.run = run
        self.page_size = page_size
        self.min_step = min_step
        self.max_step = max_step
        self.page_offset = min_step  # minStep for next page
        self.scan_offset = 0  # index within current page of rows
        self.rows = []  # current page of rows

    def __iter__(self):
        self.page_offset = self.min_step
        self.scan_offset = 0
        self.rows = []
        return self

    def __next__(self):
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset >= self.max_step:
                raise StopIteration()
            self._load_next()

    next = __next__

    @normalize_exceptions
    @retry.retriable(
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException),
    )
    def _load_next(self):
        max_step = self.page_offset + self.page_size
        if max_step > self.max_step:
            max_step = self.max_step
        variables = {
            "entity": self.run.entity,
            "project": self.run.project,
            "run": self.run.id,
            "minStep": int(self.page_offset),
            "maxStep": int(max_step),
            "pageSize": int(self.page_size),
        }

        res = self.client.execute(self.QUERY, variable_values=variables)
        res = res["project"]["run"]["history"]
        self.rows = [json.loads(row) for row in res]
        self.page_offset += self.page_size
        self.scan_offset = 0


class SampledHistoryScan:
    QUERY = gql(
        """
        query SampledHistoryPage($entity: String!, $project: String!, $run: String!, $spec: JSONString!) {
            project(name: $project, entityName: $entity) {
                run(name: $run) {
                    sampledHistory(specs: [$spec])
                }
            }
        }
        """
    )

    def __init__(self, client, run, keys, min_step, max_step, page_size=1000):
        self.client = client
        self.run = run
        self.keys = keys
        self.page_size = page_size
        self.min_step = min_step
        self.max_step = max_step
        self.page_offset = min_step  # minStep for next page
        self.scan_offset = 0  # index within current page of rows
        self.rows = []  # current page of rows

    def __iter__(self):
        self.page_offset = self.min_step
        self.scan_offset = 0
        self.rows = []
        return self

    def __next__(self):
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset >= self.max_step:
                raise StopIteration()
            self._load_next()

    next = __next__

    @normalize_exceptions
    @retry.retriable(
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException),
    )
    def _load_next(self):
        max_step = self.page_offset + self.page_size
        if max_step > self.max_step:
            max_step = self.max_step
        variables = {
            "entity": self.run.entity,
            "project": self.run.project,
            "run": self.run.id,
            "spec": json.dumps(
                {
                    "keys": self.keys,
                    "minStep": int(self.page_offset),
                    "maxStep": int(max_step),
                    "samples": int(self.page_size),
                }
            ),
        }

        res = self.client.execute(self.QUERY, variable_values=variables)
        res = res["project"]["run"]["sampledHistory"]
        self.rows = res[0]
        self.page_offset += self.page_size
        self.scan_offset = 0


class ProjectArtifactTypes(Paginator):
    QUERY = gql(
        """
        query ProjectArtifacts(
            $entityName: String!,
            $projectName: String!,
            $cursor: String,
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactTypes(after: $cursor) {
                    ...ArtifactTypesFragment
                }
            }
        }
        %s
    """
        % ARTIFACTS_TYPES_FRAGMENT
    )

    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        name: Optional[str] = None,
        per_page: Optional[int] = 50,
    ):
        self.entity = entity
        self.project = project

        variable_values = {
            "entityName": entity,
            "projectName": project,
        }

        super().__init__(client, variable_values, per_page)

    @property
    def length(self):
        # TODO
        return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["artifactTypes"]["pageInfo"][
                "hasNextPage"
            ]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["artifactTypes"]["edges"][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update({"cursor": self.cursor})

    def convert_objects(self):
        if self.last_response["project"] is None:
            return []
        return [
            ArtifactType(
                self.client, self.entity, self.project, r["node"]["name"], r["node"]
            )
            for r in self.last_response["project"]["artifactTypes"]["edges"]
        ]


def server_supports_artifact_collections_gql_edges(
    client: RetryingClient, warn: bool = False
) -> bool:
    # TODO: Validate this version
    # Edges were merged into core on Mar 2, 2022: https://github.com/wandb/core/commit/81c90b29eaacfe0a96dc1ebd83c53560ca763e8b
    # CLI version was bumped to "0.12.11" on Mar 3, 2022: https://github.com/wandb/core/commit/328396fa7c89a2178d510a1be9c0d4451f350d7b
    supported = client.version_supported("0.12.11")  # edges were merged on
    if not supported and warn:
        # First local release to include the above is 0.9.50: https://github.com/wandb/local/releases/tag/0.9.50
        wandb.termwarn(
            "W&B Local Server version does not support ArtifactCollection gql edges; falling back to using legacy ArtifactSequence. Please update server to at least version 0.9.50."
        )
    return supported


def artifact_collection_edge_name(server_supports_artifact_collections: bool) -> str:
    return (
        "artifactCollection"
        if server_supports_artifact_collections
        else "artifactSequence"
    )


def artifact_collection_plural_edge_name(
    server_supports_artifact_collections: bool,
) -> str:
    return (
        "artifactCollections"
        if server_supports_artifact_collections
        else "artifactSequences"
    )


class ProjectArtifactCollections(Paginator):
    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        type_name: str,
        per_page: Optional[int] = 50,
    ):
        self.entity = entity
        self.project = project
        self.type_name = type_name

        variable_values = {
            "entityName": entity,
            "projectName": project,
            "artifactTypeName": type_name,
        }

        self.QUERY = gql(
            """
            query ProjectArtifactCollections(
                $entityName: String!,
                $projectName: String!,
                $artifactTypeName: String!
                $cursor: String,
            ) {
                project(name: $projectName, entityName: $entityName) {
                    artifactType(name: $artifactTypeName) {
                        artifactCollections: %s(after: $cursor) {
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                            totalCount
                            edges {
                                node {
                                    id
                                    name
                                    description
                                    createdAt
                                }
                                cursor
                            }
                        }
                    }
                }
            }
        """
            % artifact_collection_plural_edge_name(
                server_supports_artifact_collections_gql_edges(client)
            )
        )

        super().__init__(client, variable_values, per_page)

    @property
    def length(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollections"][
                "totalCount"
            ]
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollections"][
                "pageInfo"
            ]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollections"][
                "edges"
            ][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update({"cursor": self.cursor})

    def convert_objects(self):
        return [
            ArtifactCollection(
                self.client,
                self.entity,
                self.project,
                r["node"]["name"],
                self.type_name,
            )
            for r in self.last_response["project"]["artifactType"][
                "artifactCollections"
            ]["edges"]
        ]


class RunArtifacts(Paginator):
    def __init__(
        self, client: Client, run: "Run", mode="logged", per_page: Optional[int] = 50
    ):
        output_query = gql(
            """
            query RunOutputArtifacts(
                $entity: String!, $project: String!, $runName: String!, $cursor: String, $perPage: Int,
            ) {
                project(name: $project, entityName: $entity) {
                    run(name: $runName) {
                        outputArtifacts(after: $cursor, first: $perPage) {
                            totalCount
                            edges {
                                node {
                                    ...ArtifactFragment
                                }
                                cursor
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
            """
            + wandb.Artifact._get_gql_artifact_fragment()
        )

        input_query = gql(
            """
            query RunInputArtifacts(
                $entity: String!, $project: String!, $runName: String!, $cursor: String, $perPage: Int,
            ) {
                project(name: $project, entityName: $entity) {
                    run(name: $runName) {
                        inputArtifacts(after: $cursor, first: $perPage) {
                            totalCount
                            edges {
                                node {
                                    ...ArtifactFragment
                                }
                                cursor
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
            """
            + wandb.Artifact._get_gql_artifact_fragment()
        )

        self.run = run
        if mode == "logged":
            self.run_key = "outputArtifacts"
            self.QUERY = output_query
        elif mode == "used":
            self.run_key = "inputArtifacts"
            self.QUERY = input_query
        else:
            raise ValueError("mode must be logged or used")

        variable_values = {
            "entity": run.entity,
            "project": run.project,
            "runName": run.id,
        }

        super().__init__(client, variable_values, per_page)

    @property
    def length(self):
        if self.last_response:
            return self.last_response["project"]["run"][self.run_key]["totalCount"]
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["run"][self.run_key]["pageInfo"][
                "hasNextPage"
            ]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["run"][self.run_key]["edges"][-1][
                "cursor"
            ]
        else:
            return None

    def convert_objects(self):
        return [
            wandb.Artifact._from_attrs(
                self.run.entity,
                self.run.project,
                "{}:v{}".format(
                    r["node"]["artifactSequence"]["name"], r["node"]["versionIndex"]
                ),
                r["node"],
                self.client,
            )
            for r in self.last_response["project"]["run"][self.run_key]["edges"]
        ]


class ArtifactType:
    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        type_name: str,
        attrs: Optional[Mapping[str, Any]] = None,
    ):
        self.client = client
        self.entity = entity
        self.project = project
        self.type = type_name
        self._attrs = attrs
        if self._attrs is None:
            self.load()

    def load(self):
        query = gql(
            """
        query ProjectArtifactType(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    id
                    name
                    description
                    createdAt
                }
            }
        }
        """
        )
        response: Optional[Mapping[str, Any]] = self.client.execute(
            query,
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactTypeName": self.type,
            },
        )
        if (
            response is None
            or response.get("project") is None
            or response["project"].get("artifactType") is None
        ):
            raise ValueError("Could not find artifact type %s" % self.type)
        self._attrs = response["project"]["artifactType"]
        return self._attrs

    @property
    def id(self):
        return self._attrs["id"]

    @property
    def name(self):
        return self._attrs["name"]

    @normalize_exceptions
    def collections(self, per_page=50):
        """Artifact collections."""
        return ProjectArtifactCollections(
            self.client, self.entity, self.project, self.type
        )

    def collection(self, name):
        return ArtifactCollection(
            self.client, self.entity, self.project, name, self.type
        )

    def __repr__(self):
        return f"<ArtifactType {self.type}>"


class ArtifactCollection:
    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        name: str,
        type: str,
        attrs: Optional[Mapping[str, Any]] = None,
    ):
        self.client = client
        self.entity = entity
        self.project = project
        self.name = name
        self.type = type
        self._attrs = attrs
        if self._attrs is None:
            self.load()
        self._aliases = [a["node"]["alias"] for a in self._attrs["aliases"]["edges"]]

    @property
    def id(self):
        return self._attrs["id"]

    @normalize_exceptions
    def versions(self, per_page=50):
        """Artifact versions."""
        return ArtifactVersions(
            self.client,
            self.entity,
            self.project,
            self.name,
            self.type,
            per_page=per_page,
        )

    @property
    def aliases(self):
        """Artifact Collection Aliases."""
        return self._aliases

    def load(self):
        query = gql(
            """
        query ArtifactCollection(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!,
            $artifactCollectionName: String!,
            $cursor: String,
            $perPage: Int = 1000
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    artifactCollection: %s(name: $artifactCollectionName) {
                        id
                        name
                        description
                        createdAt
                        aliases(after: $cursor, first: $perPage){
                            edges {
                                node {
                                    alias
                                }
                                cursor
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
        """
            % artifact_collection_edge_name(
                server_supports_artifact_collections_gql_edges(self.client)
            )
        )
        response = self.client.execute(
            query,
            variable_values={
                "entityName": self.entity,
                "projectName": self.project,
                "artifactTypeName": self.type,
                "artifactCollectionName": self.name,
            },
        )
        if (
            response is None
            or response.get("project") is None
            or response["project"].get("artifactType") is None
            or response["project"]["artifactType"].get("artifactCollection") is None
        ):
            raise ValueError("Could not find artifact type %s" % self.type)
        self._attrs = response["project"]["artifactType"]["artifactCollection"]
        return self._attrs

    @normalize_exceptions
    def is_sequence(self) -> bool:
        """Return True if this is a sequence."""
        query = gql(
            """
            query FindSequence($entity: String!, $project: String!, $collection: String!, $type: String!) {
                project(name: $project, entityName: $entity) {
                    artifactType(name: $type) {
                        __typename
                        artifactSequence(name: $collection) {
                            __typename
                        }
                    }
                }
            }
            """
        )
        variables = {
            "entity": self.entity,
            "project": self.project,
            "collection": self.name,
            "type": self.type,
        }
        res = self.client.execute(query, variable_values=variables)
        sequence = res["project"]["artifactType"]["artifactSequence"]
        return sequence is not None and sequence["__typename"] == "ArtifactSequence"

    @normalize_exceptions
    def delete(self):
        """Delete the entire artifact collection."""
        if self.is_sequence():
            mutation = gql(
                """
                mutation deleteArtifactSequence($id: ID!) {
                    deleteArtifactSequence(input: {
                        artifactSequenceID: $id
                    }) {
                        artifactCollection {
                            state
                        }
                    }
                }
                """
            )
        else:
            mutation = gql(
                """
                mutation deleteArtifactPortfolio($id: ID!) {
                    deleteArtifactPortfolio(input: {
                        artifactPortfolioID: $id
                    }) {
                        artifactCollection {
                            state
                        }
                    }
                }
                """
            )
        self.client.execute(mutation, variable_values={"id": self.id})

    def __repr__(self):
        return f"<ArtifactCollection {self.name} ({self.type})>"


class ArtifactVersions(Paginator):
    """An iterable collection of artifact versions associated with a project and optional filter.

    This is generally used indirectly via the `Api`.artifact_versions method.
    """

    def __init__(
        self,
        client: Client,
        entity: str,
        project: str,
        collection_name: str,
        type: str,
        filters: Optional[Mapping[str, Any]] = None,
        order: Optional[str] = None,
        per_page: int = 50,
    ):
        self.entity = entity
        self.collection_name = collection_name
        self.type = type
        self.project = project
        self.filters = {"state": "COMMITTED"} if filters is None else filters
        self.order = order
        variables = {
            "project": self.project,
            "entity": self.entity,
            "order": self.order,
            "type": self.type,
            "collection": self.collection_name,
            "filters": json.dumps(self.filters),
        }
        self.QUERY = gql(
            """
            query Artifacts($project: String!, $entity: String!, $type: String!, $collection: String!, $cursor: String, $perPage: Int = 50, $order: String, $filters: JSONString) {{
                project(name: $project, entityName: $entity) {{
                    artifactType(name: $type) {{
                        artifactCollection: {}(name: $collection) {{
                            name
                            artifacts(filters: $filters, after: $cursor, first: $perPage, order: $order) {{
                                totalCount
                                edges {{
                                    node {{
                                        ...ArtifactFragment
                                    }}
                                    version
                                    cursor
                                }}
                                pageInfo {{
                                    endCursor
                                    hasNextPage
                                }}
                            }}
                        }}
                    }}
                }}
            }}
            {}
            """.format(
                artifact_collection_edge_name(
                    server_supports_artifact_collections_gql_edges(client)
                ),
                wandb.Artifact._get_gql_artifact_fragment(),
            )
        )
        super().__init__(client, variables, per_page)

    @property
    def length(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollection"][
                "artifacts"
            ]["totalCount"]
        else:
            return None

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollection"][
                "artifacts"
            ]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactCollection"][
                "artifacts"
            ]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self):
        if self.last_response["project"]["artifactType"]["artifactCollection"] is None:
            return []
        return [
            wandb.Artifact._from_attrs(
                self.entity,
                self.project,
                self.collection_name + ":" + a["version"],
                a["node"],
                self.client,
            )
            for a in self.last_response["project"]["artifactType"][
                "artifactCollection"
            ]["artifacts"]["edges"]
        ]


class ArtifactFiles(Paginator):
    QUERY = gql(
        """
        query ArtifactFiles(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!,
            $artifactName: String!
            $fileNames: [String!],
            $fileCursor: String,
            $fileLimit: Int = 50
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    artifact(name: $artifactName) {
                        ...ArtifactFilesFragment
                    }
                }
            }
        }
        %s
    """
        % ARTIFACT_FILES_FRAGMENT
    )

    def __init__(
        self,
        client: Client,
        artifact: "wandb.Artifact",
        names: Optional[Sequence[str]] = None,
        per_page: int = 50,
    ):
        self.artifact = artifact
        variables = {
            "entityName": artifact.source_entity,
            "projectName": artifact.source_project,
            "artifactTypeName": artifact.type,
            "artifactName": artifact.source_name,
            "fileNames": names,
        }
        # The server must advertise at least SDK 0.12.21
        # to get storagePath
        if not client.version_supported("0.12.21"):
            self.QUERY = gql(self.QUERY.loc.source.body.replace("storagePath\n", ""))
        super().__init__(client, variables, per_page)

    @property
    def path(self):
        return [self.artifact.entity, self.artifact.project, self.artifact.name]

    @property
    def length(self):
        return self.artifact.file_count

    @property
    def more(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifact"]["files"][
                "pageInfo"
            ]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifact"]["files"][
                "edges"
            ][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update({"fileLimit": self.per_page, "fileCursor": self.cursor})

    def convert_objects(self):
        return [
            File(self.client, r["node"])
            for r in self.last_response["project"]["artifactType"]["artifact"]["files"][
                "edges"
            ]
        ]

    def __repr__(self):
        return "<ArtifactFiles {} ({})>".format("/".join(self.path), len(self))


class Job:
    _name: str
    _input_types: Type
    _output_types: Type
    _entity: str
    _project: str
    _entrypoint: List[str]
    _notebook_job: bool
    _partial: bool

    def __init__(self, api: Api, name, path: Optional[str] = None) -> None:
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
        launch_project.set_entry_point(new_entrypoint)

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
            launch_project.set_entry_point(self._entrypoint)

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
            launch_project.set_entry_point(self._entrypoint)

    def _configure_launch_project_container(self, launch_project):
        launch_project.docker_image = self._job_info.get("source", {}).get("image")
        if launch_project.docker_image is None:
            raise LaunchError(
                "Job had malformed source dictionary without an image key"
            )
        if self._entrypoint:
            launch_project.set_entry_point(self._entrypoint)

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
        project_queue=None,
    ):
        from wandb.sdk.launch import launch_add

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

        queued_run = launch_add.launch_add(
            job=self._name,
            config={"overrides": {"run_config": run_config}},
            project=project or self._project,
            entity=entity or self._entity,
            queue_name=queue,
            resource=resource,
            project_queue=project_queue,
            resource_args=resource_args,
        )
        return queued_run
