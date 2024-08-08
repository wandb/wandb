"""Use the Public API to export or update data that you have saved to W&B.

Before using this API, you'll want to log data from your script — check the
[Quickstart](https://docs.wandb.ai/quickstart) for more details.

You might use the Public API to
 - update metadata or metrics for an experiment after it has been completed,
 - pull down your results as a dataframe for post-hoc analysis in a Jupyter notebook, or
 - check your saved model artifacts for those tagged as `ready-to-deploy`.

For more on using the Public API, check out [our guide](https://docs.wandb.com/guides/track/public-api-guide).
"""

import json
import logging
import os
import urllib
from typing import Any, Dict, List, Optional

import requests
from wandb_gql import Client, gql
from wandb_gql.client import RetryError

import wandb
from wandb import env, util
from wandb.apis import public
from wandb.apis.internal import Api as InternalApi
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.public.const import RETRY_TIMEDELTA
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings
from wandb.sdk.launch.utils import LAUNCH_DEFAULT_PROJECT
from wandb.sdk.lib import retry, runid
from wandb.sdk.lib.deprecate import Deprecated, deprecate
from wandb.sdk.lib.gql_request import GraphQLSession

logger = logging.getLogger(__name__)


class RetryingClient:
    INFO_QUERY = gql(
        """
        query ServerInfo{
            serverInfo {
                cliVersionInfo
                latestLocalVersionInfo {
                    outOfDate
                    latestVersionString
                    versionOnThisInstanceString
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
    def execute(self, *args, **kwargs):  # noqa: D102  # User not encouraged to use this class directly
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

    def version_supported(self, min_version: str) -> bool:  # noqa: D102  # User not encouraged to use this class directly
        from wandb.util import parse_version

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
    DEFAULT_ENTITY_QUERY = gql(
        """
        query Viewer{
            viewer {
                id
                entity
            }
        }
        """
    )

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
        overrides: Optional[Dict[str, Any]] = None,
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
        proxies = self.settings.get("_proxies") or json.loads(
            os.environ.get("WANDB__PROXIES", "{}")
        )
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
                url="{}/graphql".format(self.settings["base_url"]),
                cookies=_thread_local_api_settings.cookies,
                proxies=proxies,
            )
        )
        self._client = RetryingClient(self._base_client)

    def create_project(self, name: str, entity: str) -> None:
        """Create a new project.

        Arguments:
            name: (str) The name of the new project.
            entity: (str) The entity of the new project.
        """
        self.client.execute(self.CREATE_PROJECT, {"entityName": entity, "name": name})

    def create_run(
        self,
        *,
        run_id: Optional[str] = None,
        project: Optional[str] = None,
        entity: Optional[str] = None,
    ) -> "public.Run":
        """Create a new run.

        Arguments:
            run_id: (str, optional) The ID to assign to the run, if given.  The run ID is automatically generated by
                default, so in general, you do not need to specify this and should only do so at your own risk.
            project: (str, optional) If given, the project of the new run.
            entity: (str, optional) If given, the entity of the new run.

        Returns:
            The newly created `Run`.
        """
        if entity is None:
            entity = self.default_entity
        return public.Run.create(self, run_id=run_id, project=project, entity=entity)

    def create_run_queue(
        self,
        name: str,
        type: "public.RunQueueResourceType",
        entity: Optional[str] = None,
        prioritization_mode: Optional["public.RunQueuePrioritizationMode"] = None,
        config: Optional[dict] = None,
        template_variables: Optional[dict] = None,
    ) -> "public.RunQueue":
        """Create a new run queue (launch).

        Arguments:
            name: (str) Name of the queue to create
            type: (str) Type of resource to be used for the queue. One of "local-container", "local-process", "kubernetes", "sagemaker", or "gcp-vertex".
            entity: (str) Optional name of the entity to create the queue. If None, will use the configured or default entity.
            prioritization_mode: (str) Optional version of prioritization to use. Either "V0" or None
            config: (dict) Optional default resource configuration to be used for the queue. Use handlebars (eg. "{{var}}") to specify template variables.
            template_variables: (dict) A dictionary of template variable schemas to be used with the config. Expected format of:
                {
                    "var-name": {
                        "schema": {
                            "type": ("string", "number", or "integer"),
                            "default": (optional value),
                            "minimum": (optional minimum),
                            "maximum": (optional maximum),
                            "enum": [..."(options)"]
                        }
                    }
                }

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

        if prioritization_mode:
            prioritization_mode = prioritization_mode.upper()
            if prioritization_mode not in ["V0"]:
                raise ValueError("prioritization_mode must be 'V0' if present")

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
            entity, type, config_json, template_variables
        )
        if not create_config_result["success"]:
            raise wandb.Error("failed to create default resource config")
        config_id = create_config_result["defaultResourceConfigID"]

        # 3. create run queue
        create_queue_result = api.create_run_queue(
            entity,
            LAUNCH_DEFAULT_PROJECT,
            name,
            "PROJECT",
            prioritization_mode,
            config_id,
        )
        if not create_queue_result["success"]:
            raise wandb.Error("failed to create run queue")

        return public.RunQueue(
            client=self.client,
            name=name,
            entity=entity,
            prioritization_mode=prioritization_mode,
            _access="PROJECT",
            _default_resource_config_id=config_id,
            _default_resource_config=config,
        )

    def create_user(self, email, admin=False):
        """Create a new user.

        Arguments:
            email: (str) The email address of the user
            admin: (bool) Whether this user should be a global instance admin

        Returns:
            A `User` object
        """
        return public.User.create(self, email, admin)

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
    def client(self) -> RetryingClient:
        return self._client

    @property
    def user_agent(self) -> str:
        return "W&B Public Client {}".format(wandb.__version__)

    @property
    def api_key(self) -> Optional[str]:
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
    def default_entity(self) -> Optional[str]:
        if self._default_entity is None:
            res = self._client.execute(self.DEFAULT_ENTITY_QUERY)
            self._default_entity = (res.get("viewer") or {}).get("entity")
        return self._default_entity

    @property
    def viewer(self) -> "public.User":
        if self._viewer is None:
            self._viewer = public.User(
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
                return public.BetaReport(
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
        project = self.settings["project"] or "uncategorized"
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
        project = self.settings["project"] or "uncategorized"
        entity = self.settings["entity"] or self.default_entity
        parts = (
            path.replace("/runs/", "/").replace("/sweeps/", "/").strip("/ ").split("/")
        )
        if ":" in parts[-1]:
            id = parts[-1].split(":")[-1]
            parts[-1] = parts[-1].split(":")[0]
        elif parts[-1]:
            id = parts[-1]
        if len(parts) == 1 and project != "uncategorized":
            pass
        elif len(parts) > 1:
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

        path, colon, alias = path.partition(":")
        full_alias = colon + alias

        parts = path.split("/")
        if len(parts) > 3:
            raise ValueError("Invalid artifact path: {}".format(path))
        elif len(parts) == 1:
            return entity, project, path + full_alias
        elif len(parts) == 2:
            return entity, parts[0], parts[1] + full_alias
        parts[-1] += full_alias
        return parts

    def projects(
        self, entity: Optional[str] = None, per_page: Optional[int] = 200
    ) -> "public.Projects":
        """Get projects for a given entity.

        Arguments:
            entity: (str) Name of the entity requested.  If None, will fall back to the
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
            self._projects[entity] = public.Projects(
                self.client, entity, per_page=per_page
            )
        return self._projects[entity]

    def project(self, name: str, entity: Optional[str] = None) -> "public.Project":
        """Return the `Project` with the given name (and entity, if given).

        Arguments:
            name: (str) The project name.
            entity: (str) Name of the entity requested.  If None, will fall back to the
                default entity passed to `Api`.  If no default entity, will raise a `ValueError`.

        Returns:
            A `Project` object.
        """
        if entity is None:
            entity = self.settings["entity"] or self.default_entity
        return public.Project(self.client, entity, name, {})

    def reports(
        self, path: str = "", name: Optional[str] = None, per_page: Optional[int] = 50
    ) -> "public.Reports":
        """Get reports for a given project path.

        WARNING: This api is in beta and will likely change in a future release

        Arguments:
            path: (str) path to project the report resides in, should be in the form: "entity/project"
            name: (str, optional) optional name of the report requested.
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
            self._reports[key] = public.Reports(
                self.client,
                public.Project(self.client, entity, project, {}),
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
        return public.Team.create(self, team, admin_username)

    def team(self, team: str) -> "public.Team":
        """Return the matching `Team` with the given name.

        Arguments:
            team: (str) The name of the team.

        Returns:
            A `Team` object.
        """
        return public.Team(self.client, team)

    def user(self, username_or_email: str) -> Optional["public.User"]:
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
        return public.User(self._client, res["users"]["edges"][0]["node"])

    def users(self, username_or_email: str) -> List["public.User"]:
        """Return all users from a partial username or email address query.

        Note: This function only works for Local Admins, if you are trying to get your own user object, please use `api.viewer`.

        Arguments:
            username_or_email: (str) The prefix or suffix of the user you want to find

        Returns:
            An array of `User` objects
        """
        res = self._client.execute(self.USERS_QUERY, {"query": username_or_email})
        return [
            public.User(self._client, edge["node"]) for edge in res["users"]["edges"]
        ]

    def runs(
        self,
        path: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        order: str = "+created_at",
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
                The default order is run.created_at from oldest to newest.
            per_page: (int) Sets the page size for query pagination.
            include_sweeps: (bool) Whether to include the sweep runs in the results.

        Returns:
            A `Runs` object, which is an iterable collection of `Run` objects.
        """
        entity, project = self._parse_project_path(path)
        filters = filters or {}
        key = (path or "") + str(filters) + str(order)
        if not self._runs.get(key):
            self._runs[key] = public.Runs(
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
            self._runs[path] = public.Run(self.client, entity, project, run_id)
        return self._runs[path]

    def queued_run(
        self,
        entity,
        project,
        queue_name,
        run_queue_item_id,
        project_queue=None,
        priority=None,
    ):
        """Return a single queued run based on the path.

        Parses paths of the form entity/project/queue_id/run_queue_item_id.
        """
        return public.QueuedRun(
            self.client,
            entity,
            project,
            queue_name,
            run_queue_item_id,
            project_queue=project_queue,
            priority=priority,
        )

    def run_queue(
        self,
        entity,
        name,
    ):
        """Return the named `RunQueue` for entity.

        To create a new `RunQueue`, use `wandb.Api().create_run_queue(...)`.
        """
        return public.RunQueue(
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
            self._sweeps[path] = public.Sweep(self.client, entity, project, sweep_id)
        return self._sweeps[path]

    @normalize_exceptions
    def artifact_types(self, project: Optional[str] = None) -> "public.ArtifactTypes":
        """Return a collection of matching artifact types.

        Arguments:
            project: (str, optional) If given, a project name or path to filter on.

        Returns:
            An iterable `ArtifactTypes` object.
        """
        entity, project = self._parse_project_path(project)
        return public.ArtifactTypes(self.client, entity, project)

    @normalize_exceptions
    def artifact_type(
        self, type_name: str, project: Optional[str] = None
    ) -> "public.ArtifactType":
        """Return the matching `ArtifactType`.

        Arguments:
            type_name: (str) The name of the artifact type to retrieve.
            project: (str, optional) If given, a project name or path to filter on.

        Returns:
            An `ArtifactType` object.
        """
        entity, project = self._parse_project_path(project)
        return public.ArtifactType(self.client, entity, project, type_name)

    @normalize_exceptions
    def artifact_collections(
        self, project_name: str, type_name: str, per_page: Optional[int] = 50
    ) -> "public.ArtifactCollections":
        """Return a collection of matching artifact collections.

        Arguments:
            project_name: (str) The name of the project to filter on.
            type_name: (str) The name of the artifact type to filter on.
            per_page: (int, optional) Sets the page size for query pagination.  None will use the default size.
                Usually there is no reason to change this.

        Returns:
            An iterable `ArtifactCollections` object.
        """
        entity, project = self._parse_project_path(project_name)
        return public.ArtifactCollections(
            self.client, entity, project, type_name, per_page=per_page
        )

    @normalize_exceptions
    def artifact_collection(
        self, type_name: str, name: str
    ) -> "public.ArtifactCollection":
        """Return a single artifact collection by type and parsing path in the form `entity/project/name`.

        Arguments:
            type_name: (str) The type of artifact collection to fetch.
            name: (str) An artifact collection name. May be prefixed with entity/project.

        Returns:
            An `ArtifactCollection` object.
        """
        entity, project, collection_name = self._parse_artifact_path(name)
        return public.ArtifactCollection(
            self.client, entity, project, collection_name, type_name
        )

    @normalize_exceptions
    def artifact_versions(self, type_name, name, per_page=50):
        """Deprecated, use `artifacts(type_name, name)` instead."""
        deprecate(
            field_name=Deprecated.api__artifact_versions,
            warning_message=(
                "Api.artifact_versions(type_name, name) is deprecated, "
                "use Api.artifacts(type_name, name) instead."
            ),
        )
        return self.artifacts(type_name, name, per_page=per_page)

    @normalize_exceptions
    def artifacts(
        self, type_name: str, name: str, per_page: Optional[int] = 50
    ) -> "public.Artifacts":
        """Return an `Artifacts` collection from the given parameters.

        Arguments:
            type_name: (str) The type of artifacts to fetch.
            name: (str) An artifact collection name. May be prefixed with entity/project.
            per_page: (int, optional) Sets the page size for query pagination.  None will use the default size.
                Usually there is no reason to change this.

        Returns:
            An iterable `Artifacts` object.
        """
        entity, project, collection_name = self._parse_artifact_path(name)
        return public.Artifacts(
            self.client, entity, project, collection_name, type_name, per_page=per_page
        )

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
    def job(self, name: Optional[str], path: Optional[str] = None) -> "public.Job":
        """Return a `Job` from the given parameters.

        Arguments:
            name: (str) The job name.
            path: (str, optional) If given, the root path in which to download the job artifact.

        Returns:
            A `Job` object.
        """
        if name is None:
            raise ValueError("You must specify name= to fetch a job.")
        elif name.count("/") != 2 or ":" not in name:
            raise ValueError(
                "Invalid job specification. A job must be of the form: <entity>/<project>/<job-name>:<alias-or-version>"
            )
        return public.Job(self, name, path)

    @normalize_exceptions
    def list_jobs(self, entity: str, project: str) -> List[Dict[str, Any]]:
        """Return a list of jobs, if any, for the given entity and project.

        Arguments:
            entity: (str) The entity for the listed job(s).
            project: (str) The project for the listed job(s).

        Returns:
            A list of matching jobs.
        """
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

    @normalize_exceptions
    def artifact_exists(self, name: str, type: Optional[str] = None) -> bool:
        """Return whether an artifact version exists within a specified project and entity.

        Arguments:
            name: (str) An artifact name. May be prefixed with entity/project.
                If entity or project is not specified, it will be inferred from the override params if populated.
                Otherwise, entity will be pulled from the user settings and project will default to "uncategorized".
                Valid names can be in the following forms:
                    name:version
                    name:alias
            type: (str, optional) The type of artifact

        Returns:
            True if the artifact version exists, False otherwise.
        """
        try:
            self.artifact(name, type)
            return True
        except wandb.errors.CommError:
            return False

    @normalize_exceptions
    def artifact_collection_exists(self, name: str, type: str) -> bool:
        """Return whether an artifact collection exists within a specified project and entity.

        Arguments:
            name: (str) An artifact collection name. May be prefixed with entity/project.
                If entity or project is not specified, it will be inferred from the override params if populated.
                Otherwise, entity will be pulled from the user settings and project will default to "uncategorized".
            type: (str) The type of artifact collection

        Returns:
            True if the artifact collection exists, False otherwise.
        """
        try:
            self.artifact_collection(type, name)
            return True
        except wandb.errors.CommError:
            return False
