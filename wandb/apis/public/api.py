"""Use the Public API to export or update data that you have saved to W&B.

Before using this API, you'll want to log data from your script — check the
[Quickstart](https://docs.wandb.ai/quickstart) for more details.

You might use the Public API to
 - update metadata or metrics for an experiment after it has been completed,
 - pull down your results as a dataframe for post-hoc analysis in a Jupyter notebook, or
 - check your saved model artifacts for those tagged as `ready-to-deploy`.

For more on using the Public API, check out [our guide](https://docs.wandb.com/guides/track/public-api-guide).
"""

from __future__ import annotations

import json
import logging
import os
import urllib
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Iterator, Literal

import requests
from pydantic import ValidationError
from typing_extensions import Unpack
from wandb_gql import Client, gql
from wandb_gql.client import RetryError

import wandb
from wandb import env, util
from wandb._analytics import tracked
from wandb._iterutils import one
from wandb._strutils import nameof
from wandb.apis import public
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.public.const import RETRY_TIMEDELTA
from wandb.apis.public.registries import Registries, Registry
from wandb.apis.public.registries._utils import fetch_org_entity_from_organization
from wandb.apis.public.utils import (
    PathType,
    fetch_org_from_settings_or_entity,
    gql_compat,
    parse_org_from_registry_path,
)
from wandb.proto.wandb_deprecated import Deprecated
from wandb.proto.wandb_internal_pb2 import ServerFeature
from wandb.sdk import wandb_login
from wandb.sdk.artifacts._validators import (
    ArtifactPath,
    FullArtifactPath,
    is_artifact_registry_project,
)
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.internal.thread_local_settings import _thread_local_api_settings
from wandb.sdk.launch.utils import LAUNCH_DEFAULT_PROJECT
from wandb.sdk.lib import retry, runid
from wandb.sdk.lib.deprecate import deprecate
from wandb.sdk.lib.gql_request import GraphQLSession

if TYPE_CHECKING:
    from wandb.automations import (
        ActionType,
        Automation,
        EventType,
        Integration,
        NewAutomation,
        SlackIntegration,
        WebhookIntegration,
    )
    from wandb.automations._utils import WriteAutomationsKwargs
    from wandb.sdk.artifacts.artifact import Artifact

    from .artifacts import (
        ArtifactCollection,
        ArtifactCollections,
        Artifacts,
        ArtifactType,
        ArtifactTypes,
    )
    from .teams import Team
    from .users import User

logger = logging.getLogger(__name__)


class RetryingClient:
    """A GraphQL client that retries requests on failure.

    <!-- lazydoc-ignore-class: internal -->
    """

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
    def execute(
        self, *args, **kwargs
    ):  # User not encouraged to use this class directly
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

    def version_supported(
        self, min_version: str
    ) -> bool:  # User not encouraged to use this class directly
        from packaging.version import parse

        return parse(min_version) <= parse(
            self.server_info["cliVersionInfo"]["max_cli_version"]
        )


class Api:
    """Used for querying the W&B server.

    Examples:
    ```python
    import wandb

    wandb.Api()
    ```
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
        overrides: dict[str, Any] | None = None,
        timeout: int | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize the API.

        Args:
            overrides: You can set `base_url` if you are
                using a W&B server other than `https://api.wandb.ai`. You can also
                set defaults for `entity`, `project`, and `run`.
            timeout: HTTP timeout in seconds for API requests. If not
                specified, the default timeout will be used.
            api_key: API key to use for authentication. If not provided,
                the API key from the current environment or configuration will be used.
                Prompts for an API key if none is provided
                or configured in the environment.
        """
        self.settings = InternalApi().settings()

        _overrides = overrides or {}
        self.settings.update(_overrides)
        self.settings["base_url"] = self.settings["base_url"].rstrip("/")
        if "organization" in _overrides:
            self.settings["organization"] = _overrides["organization"]
        if "username" in _overrides and "entity" not in _overrides:
            wandb.termwarn(
                'Passing "username" to Api is deprecated. please use "entity" instead.'
            )
            self.settings["entity"] = _overrides["username"]

        if _thread_local_api_settings.cookies is None:
            self.api_key = self._load_api_key(
                base_url=self.settings["base_url"],
                init_api_key=api_key,
            )
            wandb_login._verify_login(
                key=self.api_key,
                base_url=self.settings["base_url"],
            )

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
        self._sentry = wandb.analytics.sentry.Sentry()
        self._configure_sentry()

    def _load_api_key(
        self,
        base_url: str,
        init_api_key: str | None = None,
    ) -> str:
        """Attempts to load a configured API key or prompt if one is not found.

        The API key is loaded in the following order:
            1. Thread local api key
            2. User explicitly provided api key
            3. Environment variable
            4. Netrc file
            5. Prompt for api key using wandb.login
        """
        # just use thread local api key if it's set
        if _thread_local_api_settings.api_key:
            return _thread_local_api_settings.api_key
        if init_api_key is not None:
            return init_api_key
        if os.getenv("WANDB_API_KEY"):
            return os.environ["WANDB_API_KEY"]

        auth = requests.utils.get_netrc_auth(base_url)
        if auth:
            return auth[-1]

        _, prompted_key = wandb_login._login(
            host=base_url,
            key=None,
            # We will explicitly verify the key later
            verify=False,
            _silent=(
                self.settings.get("silent", False) or self.settings.get("quiet", False)
            ),
            update_api_key=False,
            _disable_warning=True,
        )
        return prompted_key

    def _configure_sentry(self) -> None:
        try:
            viewer = self.viewer
        except (ValueError, requests.RequestException):
            # we need the viewer to configure the entity, and user email
            return

        email = viewer.email if viewer else None
        entity = self.default_entity

        self._sentry.configure_scope(
            tags={
                "entity": entity,
                "email": email,
            },
        )

    def create_project(self, name: str, entity: str) -> None:
        """Create a new project.

        Args:
            name: The name of the new project.
            entity: The entity of the new project.
        """
        self.client.execute(self.CREATE_PROJECT, {"entityName": entity, "name": name})

    def create_run(
        self,
        *,
        run_id: str | None = None,
        project: str | None = None,
        entity: str | None = None,
    ) -> public.Run:
        """Create a new run.

        Args:
            run_id: The ID to assign to the run. If not specified, W&B
                creates a random ID.
            project: The project where to log the run to. If no project is specified,
                log the run to a project called "Uncategorized".
            entity: The entity that owns the project. If no entity is
                specified, log the run to the default entity.

        Returns:
            The newly created `Run`.
        """
        if entity is None:
            entity = self.default_entity
        return public.Run.create(self, run_id=run_id, project=project, entity=entity)

    def create_run_queue(
        self,
        name: str,
        type: public.RunQueueResourceType,
        entity: str | None = None,
        prioritization_mode: public.RunQueuePrioritizationMode | None = None,
        config: dict | None = None,
        template_variables: dict | None = None,
    ) -> public.RunQueue:
        """Create a new run queue in W&B Launch.

        Args:
            name: Name of the queue to create
            type: Type of resource to be used for the queue. One of
                "local-container", "local-process", "kubernetes","sagemaker",
                or "gcp-vertex".
            entity: Name of the entity to create the queue. If `None`, use
                the configured or default entity.
            prioritization_mode: Version of prioritization to use.
                Either "V0" or `None`.
            config: Default resource configuration to be used for the queue.
                Use handlebars (eg. `{{var}}`) to specify template variables.
            template_variables: A dictionary of template variable schemas to
                use with the config.

        Returns:
            The newly created `RunQueue`.

        Raises:
            `ValueError` if any of the parameters are invalid
            `wandb.Error` on wandb API errors
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

    def create_custom_chart(
        self,
        entity: str,
        name: str,
        display_name: str,
        spec_type: Literal["vega2"],
        access: Literal["private", "public"],
        spec: str | dict,
    ) -> str:
        """Create a custom chart preset and return its id.

        Args:
            entity: The entity (user or team) that owns the chart
            name: Unique identifier for the chart preset
            display_name: Human-readable name shown in the UI
            spec_type: Type of specification. Must be "vega2" for Vega-Lite v2 specifications.
            access: Access level for the chart:
                - "private": Chart is only accessible to the entity that created it
                - "public": Chart is publicly accessible
            spec: The Vega/Vega-Lite specification as a dictionary or JSON string

        Returns:
            The ID of the created chart preset in the format "entity/name"

        Raises:
            wandb.Error: If chart creation fails
            UnsupportedError: If the server doesn't support custom charts

        Example:
            ```python
            import wandb

            api = wandb.Api()

            # Define a simple bar chart specification
            vega_spec = {
                "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
                "mark": "bar",
                "data": {"name": "wandb"},
                "encoding": {
                    "x": {"field": "${field:x}", "type": "ordinal"},
                    "y": {"field": "${field:y}", "type": "quantitative"},
                },
            }

            # Create the custom chart
            chart_id = api.create_custom_chart(
                entity="my-team",
                name="my-bar-chart",
                display_name="My Custom Bar Chart",
                spec_type="vega2",
                access="private",
                spec=vega_spec,
            )

            # Use with wandb.plot_table()
            chart = wandb.plot_table(
                vega_spec_name=chart_id,
                data_table=my_table,
                fields={"x": "category", "y": "value"},
            )
            ```
        """
        # Convert user-facing lowercase access to backend uppercase
        backend_access = access.upper()

        api = InternalApi(retry_timedelta=RETRY_TIMEDELTA)
        result = api.create_custom_chart(
            entity=entity,
            name=name,
            display_name=display_name,
            spec_type=spec_type,
            access=backend_access,
            spec=spec,
        )
        if result is None or result.get("chart") is None:
            raise wandb.Error("failed to create custom chart")
        return result["chart"]["id"]

    def upsert_run_queue(
        self,
        name: str,
        resource_config: dict,
        resource_type: public.RunQueueResourceType,
        entity: str | None = None,
        template_variables: dict | None = None,
        external_links: dict | None = None,
        prioritization_mode: public.RunQueuePrioritizationMode | None = None,
    ):
        """Upsert a run queue in W&B Launch.

        Args:
            name: Name of the queue to create
            entity: Optional name of the entity to create the queue. If `None`,
                use the configured or default entity.
            resource_config: Optional default resource configuration to be used
                for the queue. Use handlebars (eg. `{{var}}`) to specify
                template variables.
            resource_type: Type of resource to be used for the queue. One of
                "local-container", "local-process", "kubernetes", "sagemaker",
                or "gcp-vertex".
            template_variables: A dictionary of template variable schemas to
                be used with the config.
            external_links: Optional dictionary of external links to be used
                with the queue.
            prioritization_mode: Optional version of prioritization to use.
                Either "V0" or None

        Returns:
            The upserted `RunQueue`.

        Raises:
            ValueError if any of the parameters are invalid
            wandb.Error on wandb API errors
        """
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

        prioritization_mode = prioritization_mode or "DISABLED"
        prioritization_mode = prioritization_mode.upper()
        if prioritization_mode not in ["V0", "DISABLED"]:
            raise ValueError(
                "prioritization_mode must be 'V0' or 'DISABLED' if present"
            )

        if resource_type not in [
            "local-container",
            "local-process",
            "kubernetes",
            "sagemaker",
            "gcp-vertex",
        ]:
            raise ValueError(
                "resource_type must be one of 'local-container', 'local-process', 'kubernetes', 'sagemaker', or 'gcp-vertex'"
            )

        self.create_project(LAUNCH_DEFAULT_PROJECT, entity)
        api = InternalApi(
            default_settings={
                "entity": entity,
                "project": self.project(LAUNCH_DEFAULT_PROJECT),
            },
            retry_timedelta=RETRY_TIMEDELTA,
        )
        # User provides external_links as a dict with name: url format
        # but backend stores it as a list of dicts with url and label keys.
        external_links = external_links or {}
        external_links = {
            "links": [
                {
                    "label": key,
                    "url": value,
                }
                for key, value in external_links.items()
            ]
        }
        upsert_run_queue_result = api.upsert_run_queue(
            name,
            entity,
            resource_type,
            {"resource_args": {resource_type: resource_config}},
            template_variables=template_variables,
            external_links=external_links,
            prioritization_mode=prioritization_mode,
        )
        if not upsert_run_queue_result["success"]:
            raise wandb.Error("failed to create run queue")
        schema_errors = (
            upsert_run_queue_result.get("configSchemaValidationErrors") or []
        )
        for error in schema_errors:
            wandb.termwarn(f"resource config validation: {error}")

        return public.RunQueue(
            client=self.client,
            name=name,
            entity=entity,
        )

    def create_user(self, email: str, admin: bool | None = False) -> User:
        """Create a new user.

        Args:
            email: The email address of the user.
            admin: Set user as a global instance administrator.

        Returns:
            A `User` object.
        """
        from .users import User

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
    def client(self) -> RetryingClient:
        """Returns the client object."""
        return self._client

    @property
    def user_agent(self) -> str:
        """Returns W&B public user agent."""
        return "W&B Public Client {}".format(wandb.__version__)

    @property
    def default_entity(self) -> str | None:
        """Returns the default W&B entity."""
        if self._default_entity is None:
            res = self._client.execute(self.DEFAULT_ENTITY_QUERY)
            self._default_entity = (res.get("viewer") or {}).get("entity")
        return self._default_entity

    @property
    def viewer(self) -> User:
        """Returns the viewer object.

        Raises:
            ValueError: If viewer data is not able to be fetched from W&B.
            requests.RequestException: If an error occurs while making the graphql request.
        """
        from .users import User

        if self._viewer is None:
            viewer = self._client.execute(self.VIEWER_QUERY).get("viewer")

            if viewer is None:
                raise ValueError(
                    "Unable to fetch user data from W&B,"
                    " please verify your API key is valid."
                )

            self._viewer = User(self._client, viewer)
            self._default_entity = self._viewer.entity
        return self._viewer

    def flush(self):
        """Flush the local cache.

        The api object keeps a local cache of runs, so if the state of the run
        may change while executing your script you must clear the local cache
        with `api.flush()` to get the latest values associated with the run.
        """
        self._runs = {}

    def from_path(self, path: str):
        """Return a run, sweep, project or report from a path.

        Args:
            path: The path to the project, run, sweep or report

        Returns:
            A `Project`, `Run`, `Sweep`, or `BetaReport` instance.

        Raises:
            `wandb.Error` if path is invalid or the object doesn't exist.

        Examples:
        In the proceeding code snippets "project", "team", "run_id", "sweep_id",
        and "report_name" are placeholders for the project, team, run ID,
        sweep ID, and the name of a specific report, respectively.

        ```python
        import wandb

        api = wandb.Api()

        project = api.from_path("project")
        team_project = api.from_path("team/project")
        run = api.from_path("team/project/runs/run_id")
        sweep = api.from_path("team/project/sweeps/sweep_id")
        report = api.from_path("team/project/reports/report_name")
        ```
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
                        "displayName": urllib.parse.unquote(name.replace("-", " ")),
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

        parsed = ArtifactPath.from_str(path)
        parsed = parsed.with_defaults(prefix=entity, project=project)
        return parsed.prefix, parsed.project, parsed.name

    def projects(
        self, entity: str | None = None, per_page: int = 200
    ) -> public.Projects:
        """Get projects for a given entity.

        Args:
            entity: Name of the entity requested.  If None, will fall back to
                the default entity passed to `Api`.  If no default entity,
                will raise a `ValueError`.
            per_page: Sets the page size for query pagination. If set to `None`,
                use the default size. Usually there is no reason to change this.

        Returns:
            A `Projects` object which is an iterable collection of `Project`objects.
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

    def project(self, name: str, entity: str | None = None) -> public.Project:
        """Return the `Project` with the given name (and entity, if given).

        Args:
            name: The project name.
            entity: Name of the entity requested.  If None, will fall back to the
                default entity passed to `Api`.  If no default entity, will
                raise a `ValueError`.

        Returns:
            A `Project` object.
        """
        # For registry artifacts, capture potential org user inputted before resolving entity
        org = entity if is_artifact_registry_project(name) else ""

        if entity is None:
            entity = self.settings["entity"] or self.default_entity

        # For registry artifacts, resolve org-based entity
        if is_artifact_registry_project(name):
            settings_entity = self.settings["entity"] or self.default_entity
            entity = InternalApi()._resolve_org_entity_name(
                entity=settings_entity, organization=org
            )
        return public.Project(self.client, entity, name, {})

    def reports(
        self, path: str = "", name: str | None = None, per_page: int = 50
    ) -> public.Reports:
        """Get reports for a given project path.

        Note: `wandb.Api.reports()` API is in beta and will likely change in
        future releases.

        Args:
            path: The path to the project the report resides in. Specify the
                entity that created the project as a prefix followed by a
                forward slash.
            name: Name of the report requested.
            per_page: Sets the page size for query pagination. If set to
                `None`, use the default size. Usually there is no reason to
                change this.

        Returns:
            A `Reports` object which is an iterable collection of
                `BetaReport` objects.

        Examples:
        ```python
        import wandb

        wandb.Api.reports("entity/project")
        ```
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

    def create_team(self, team: str, admin_username: str | None = None) -> Team:
        """Create a new team.

        Args:
            team: The name of the team
            admin_username: Username of the admin user of the team.
                Defaults to the current user.

        Returns:
            A `Team` object.
        """
        from .teams import Team

        return Team.create(self, team, admin_username)

    def team(self, team: str) -> Team:
        """Return the matching `Team` with the given name.

        Args:
            team: The name of the team.

        Returns:
            A `Team` object.
        """
        from .teams import Team

        return Team(self.client, team)

    def user(self, username_or_email: str) -> User | None:
        """Return a user from a username or email address.

        This function only works for local administrators. Use `api.viewer`
            to get your own user object.

        Args:
            username_or_email: The username or email address of the user.

        Returns:
            A `User` object or None if a user is not found.
        """
        from .users import User

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

    def users(self, username_or_email: str) -> list[User]:
        """Return all users from a partial username or email address query.

        This function only works for local administrators. Use `api.viewer`
            to get your own user object.

        Args:
            username_or_email: The prefix or suffix of the user you want to find.

        Returns:
            An array of `User` objects.
        """
        from .users import User

        res = self._client.execute(self.USERS_QUERY, {"query": username_or_email})
        return [User(self._client, edge["node"]) for edge in res["users"]["edges"]]

    def runs(
        self,
        path: str | None = None,
        filters: dict[str, Any] | None = None,
        order: str = "+created_at",
        per_page: int = 50,
        include_sweeps: bool = True,
        lazy: bool = True,
    ):
        """Returns a `Runs` object, which lazily iterates over `Run` objects.

        Fields you can filter by include:
        - `createdAt`: The timestamp when the run was created. (in ISO 8601 format, e.g. "2023-01-01T12:00:00Z")
        - `displayName`: The human-readable display name of the run. (e.g. "eager-fox-1")
        - `duration`: The total runtime of the run in seconds.
        - `group`: The group name used to organize related runs together.
        - `host`: The hostname where the run was executed.
        - `jobType`: The type of job or purpose of the run.
        - `name`: The unique identifier of the run. (e.g. "a1b2cdef")
        - `state`: The current state of the run.
        - `tags`: The tags associated with the run.
        - `username`: The username of the user who initiated the run

        Additionally, you can filter by items in the run config or summary metrics.
        Such as `config.experiment_name`, `summary_metrics.loss`, etc.

        For more complex filtering, you can use MongoDB query operators.
        For details, see: https://docs.mongodb.com/manual/reference/operator/query
        The following operations are supported:
        - `$and`
        - `$or`
        - `$nor`
        - `$eq`
        - `$ne`
        - `$gt`
        - `$gte`
        - `$lt`
        - `$lte`
        - `$in`
        - `$nin`
        - `$exists`
        - `$regex`



        Args:
            path: (str) path to project, should be in the form: "entity/project"
            filters: (dict) queries for specific runs using the MongoDB query language.
                You can filter by run properties such as config.key, summary_metrics.key, state, entity, createdAt, etc.
                For example: `{"config.experiment_name": "foo"}` would find runs with a config entry
                    of experiment name set to "foo"
            order: (str) Order can be `created_at`, `heartbeat_at`, `config.*.value`, or `summary_metrics.*`.
                If you prepend order with a + order is ascending (default).
                If you prepend order with a - order is descending.
                The default order is run.created_at from oldest to newest.
            per_page: (int) Sets the page size for query pagination.
            include_sweeps: (bool) Whether to include the sweep runs in the results.
            lazy: (bool) Whether to use lazy loading for faster performance.
                When True (default), only essential run metadata is loaded initially.
                Heavy fields like config, summaryMetrics, and systemMetrics are loaded
                on-demand when accessed. Set to False for full data upfront.

        Returns:
            A `Runs` object, which is an iterable collection of `Run` objects.

        Examples:
        ```python
        # Find runs in project where config.experiment_name has been set to "foo"
        api.runs(path="my_entity/project", filters={"config.experiment_name": "foo"})
        ```

        ```python
        # Find runs in project where config.experiment_name has been set to "foo" or "bar"
        api.runs(
            path="my_entity/project",
            filters={
                "$or": [
                    {"config.experiment_name": "foo"},
                    {"config.experiment_name": "bar"},
                ]
            },
        )
        ```

        ```python
        # Find runs in project where config.experiment_name matches a regex
        # (anchors are not supported)
        api.runs(
            path="my_entity/project",
            filters={"config.experiment_name": {"$regex": "b.*"}},
        )
        ```

        ```python
        # Find runs in project where the run name matches a regex
        # (anchors are not supported)
        api.runs(
            path="my_entity/project", filters={"display_name": {"$regex": "^foo.*"}}
        )
        ```

        ```python
        # Find runs in project sorted by ascending loss
        api.runs(path="my_entity/project", order="+summary_metrics.loss")
        ```
        """
        entity, project = self._parse_project_path(path)
        filters = filters or {}
        key = (path or "") + str(filters) + str(order)

        # Check if we have cached results
        if self._runs.get(key):
            cached_runs = self._runs[key]
            # If requesting full data but cached data is lazy, upgrade it
            if not lazy and cached_runs._lazy:
                cached_runs.upgrade_to_full()
            return cached_runs

        # Create new Runs object
        self._runs[key] = public.Runs(
            self.client,
            entity,
            project,
            filters=filters,
            order=order,
            per_page=per_page,
            include_sweeps=include_sweeps,
            lazy=lazy,
        )
        return self._runs[key]

    @normalize_exceptions
    def run(self, path=""):
        """Return a single run by parsing path in the form `entity/project/run_id`.

        Args:
            path: Path to run in the form `entity/project/run_id`.
                If `api.entity` is set, this can be in the form `project/run_id`
                and if `api.project` is set this can just be the run_id.

        Returns:
            A `Run` object.
        """
        entity, project, run_id = self._parse_path(path)
        if not self._runs.get(path):
            # Individual runs should load full data by default
            self._runs[path] = public.Run(
                self.client, entity, project, run_id, lazy=False
            )
        return self._runs[path]

    def queued_run(
        self,
        entity: str,
        project: str,
        queue_name: str,
        run_queue_item_id: str,
        project_queue=None,
        priority=None,
    ):
        """Return a single queued run based on the path.

        Parses paths of the form `entity/project/queue_id/run_queue_item_id`.
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
        entity: str,
        name: str,
    ):
        """Return the named `RunQueue` for entity.

        See `Api.create_run_queue` for more information on how to create a run queue.
        """
        return public.RunQueue(
            self.client,
            name,
            entity,
        )

    @normalize_exceptions
    def sweep(self, path=""):
        """Return a sweep by parsing path in the form `entity/project/sweep_id`.

        Args:
            path: Path to sweep in the form entity/project/sweep_id.
                If `api.entity` is set, this can be in the form
                project/sweep_id and if `api.project` is set
                this can just be the sweep_id.

        Returns:
            A `Sweep` object.
        """
        entity, project, sweep_id = self._parse_path(path)
        if not self._sweeps.get(path):
            self._sweeps[path] = public.Sweep(self.client, entity, project, sweep_id)
        return self._sweeps[path]

    @normalize_exceptions
    def artifact_types(self, project: str | None = None) -> ArtifactTypes:
        """Returns a collection of matching artifact types.

        Args:
            project: The project name or path to filter on.

        Returns:
            An iterable `ArtifactTypes` object.
        """
        from .artifacts import ArtifactTypes

        project_path = project
        entity, project = self._parse_project_path(project_path)
        # If its a Registry project, the entity is considered to be an org instead
        if is_artifact_registry_project(project):
            settings_entity = self.settings["entity"] or self.default_entity
            org = parse_org_from_registry_path(project_path, PathType.PROJECT)
            entity = InternalApi()._resolve_org_entity_name(
                entity=settings_entity, organization=org
            )
        return ArtifactTypes(self.client, entity, project)

    @normalize_exceptions
    def artifact_type(self, type_name: str, project: str | None = None) -> ArtifactType:
        """Returns the matching `ArtifactType`.

        Args:
            type_name: The name of the artifact type to retrieve.
            project: If given, a project name or path to filter on.

        Returns:
            An `ArtifactType` object.
        """
        from .artifacts import ArtifactType

        project_path = project
        entity, project = self._parse_project_path(project_path)
        # If its an Registry artifact, the entity is an org instead
        if is_artifact_registry_project(project):
            org = parse_org_from_registry_path(project_path, PathType.PROJECT)
            settings_entity = self.settings["entity"] or self.default_entity
            entity = InternalApi()._resolve_org_entity_name(
                entity=settings_entity, organization=org
            )
        return ArtifactType(self.client, entity, project, type_name)

    @normalize_exceptions
    def artifact_collections(
        self, project_name: str, type_name: str, per_page: int = 50
    ) -> ArtifactCollections:
        """Returns a collection of matching artifact collections.

        Args:
            project_name: The name of the project to filter on.
            type_name: The name of the artifact type to filter on.
            per_page: Sets the page size for query pagination.  None will use the default size.
                Usually there is no reason to change this.

        Returns:
            An iterable `ArtifactCollections` object.
        """
        from .artifacts import ArtifactCollections

        entity, project = self._parse_project_path(project_name)
        # If iterating through Registry project, the entity is considered to be an org instead
        if is_artifact_registry_project(project):
            org = parse_org_from_registry_path(project_name, PathType.PROJECT)
            settings_entity = self.settings["entity"] or self.default_entity
            entity = InternalApi()._resolve_org_entity_name(
                entity=settings_entity, organization=org
            )
        return ArtifactCollections(
            self.client, entity, project, type_name, per_page=per_page
        )

    @normalize_exceptions
    def artifact_collection(self, type_name: str, name: str) -> ArtifactCollection:
        """Returns a single artifact collection by type.

        You can use the returned `ArtifactCollection` object to retrieve
        information about specific artifacts in that collection, and more.

        Args:
            type_name: The type of artifact collection to fetch.
            name: An artifact collection name. Optionally append the entity
                that logged the artifact as a prefix followed by a forward
                slash.

        Returns:
            An `ArtifactCollection` object.

        Examples:
        In the proceeding code snippet "type", "entity", "project", and
        "artifact_name" are placeholders for the collection type, your W&B
        entity, name of the project the artifact is in, and the name of
        the artifact, respectively.

        ```python
        import wandb

        collections = wandb.Api().artifact_collection(
            type_name="type", name="entity/project/artifact_name"
        )

        # Get the first artifact in the collection
        artifact_example = collections.artifacts()[0]

        # Download the contents of the artifact to the specified root directory.
        artifact_example.download()
        ```
        """
        from .artifacts import ArtifactCollection

        entity, project, collection_name = self._parse_artifact_path(name)
        # If its an Registry artifact, the entity is considered to be an org instead
        if is_artifact_registry_project(project):
            org = parse_org_from_registry_path(name, PathType.ARTIFACT)
            settings_entity = self.settings["entity"] or self.default_entity
            entity = InternalApi()._resolve_org_entity_name(
                entity=settings_entity, organization=org
            )

        if entity is None:
            raise ValueError(
                "Could not determine entity. Please include the entity as part of the collection name path."
            )

        return ArtifactCollection(
            self.client, entity, project, collection_name, type_name
        )

    @normalize_exceptions
    def artifact_versions(self, type_name, name, per_page=50):
        """Deprecated. Use `Api.artifacts(type_name, name)` method instead."""
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
        self,
        type_name: str,
        name: str,
        per_page: int = 50,
        tags: list[str] | None = None,
    ) -> Artifacts:
        """Return an `Artifacts` collection.

        Args:
        type_name: The type of artifacts to fetch.
        name: The artifact's collection name. Optionally append the
            entity that logged the artifact as a prefix followed by
            a forward slash.
        per_page: Sets the page size for query pagination. If set to
            `None`, use the default size. Usually there is no reason
            to change this.
        tags: Only return artifacts with all of these tags.

        Returns:
            An iterable `Artifacts` object.

        Examples:
        In the proceeding code snippet, "type", "entity", "project", and
        "artifact_name" are placeholders for the artifact type, W&B entity,
        name of the project the artifact was logged to,
        and the name of the artifact, respectively.

        ```python
        import wandb

        wandb.Api().artifacts(type_name="type", name="entity/project/artifact_name")
        ```
        """
        from .artifacts import Artifacts

        entity, project, collection_name = self._parse_artifact_path(name)
        # If its an Registry project, the entity is considered to be an org instead
        if is_artifact_registry_project(project):
            org = parse_org_from_registry_path(name, PathType.ARTIFACT)
            settings_entity = self.settings["entity"] or self.default_entity
            entity = InternalApi()._resolve_org_entity_name(
                entity=settings_entity, organization=org
            )
        return Artifacts(
            self.client,
            entity,
            project,
            collection_name,
            type_name,
            per_page=per_page,
            tags=tags,
        )

    @normalize_exceptions
    def _artifact(
        self, name: str, type: str | None = None, enable_tracking: bool = False
    ) -> Artifact:
        from wandb.sdk.artifacts.artifact import Artifact

        if name is None:
            raise ValueError("You must specify name= to fetch an artifact.")
        entity, project, artifact_name = self._parse_artifact_path(name)

        # If its an Registry artifact, the entity is an org instead
        if is_artifact_registry_project(project):
            organization = (
                name.split("/")[0]
                if name.count("/") == 2
                else self.settings["organization"]
            )
            # set entity to match the settings since in above code it was potentially set to an org
            settings_entity = self.settings["entity"] or self.default_entity
            # Registry artifacts are under the org entity. Because we offer a shorthand and alias for this path,
            # we need to fetch the org entity to for the user behind the scenes.
            entity = InternalApi()._resolve_org_entity_name(
                entity=settings_entity, organization=organization
            )

        if entity is None:
            raise ValueError(
                "Could not determine entity. Please include the entity as part of the artifact name path."
            )

        path = FullArtifactPath(prefix=entity, project=project, name=artifact_name)
        artifact = Artifact._from_name(
            path=path,
            client=self.client,
            enable_tracking=enable_tracking,
        )
        if type is not None and artifact.type != type:
            raise ValueError(
                f"type {type} specified but this artifact is of type {artifact.type}"
            )
        return artifact

    @normalize_exceptions
    def artifact(self, name: str, type: str | None = None):
        """Returns a single artifact.

        Args:
            name: The artifact's name. The name of an artifact resembles a
                filepath that consists, at a minimum, the name of the project
                the artifact was logged to, the name of the artifact, and the
                artifact's version or alias. Optionally append the entity that
                logged the artifact as a prefix followed by a forward slash.
                If no entity is specified in the name, the Run or API
                setting's entity is used.
            type: The type of artifact to fetch.

        Returns:
            An `Artifact` object.

        Raises:
            ValueError: If the artifact name is not specified.
            ValueError: If the artifact type is specified but does not
                match the type of the fetched artifact.

        Examples:
        In the proceeding code snippets "entity", "project", "artifact",
        "version", and "alias" are placeholders for your W&B entity, name
        of the project the artifact is in, the name of the artifact,
        and artifact's version, respectively.

        ```python
        import wandb

        # Specify the project, artifact's name, and the artifact's alias
        wandb.Api().artifact(name="project/artifact:alias")

        # Specify the project, artifact's name, and a specific artifact version
        wandb.Api().artifact(name="project/artifact:version")

        # Specify the entity, project, artifact's name, and the artifact's alias
        wandb.Api().artifact(name="entity/project/artifact:alias")

        # Specify the entity, project, artifact's name, and a specific artifact version
        wandb.Api().artifact(name="entity/project/artifact:version")
        ```

        Note:
        This method is intended for external use only. Do not call `api.artifact()` within the wandb repository code.
        """
        return self._artifact(name=name, type=type, enable_tracking=True)

    @normalize_exceptions
    def job(self, name: str | None, path: str | None = None) -> public.Job:
        """Return a `Job` object.

        Args:
            name: The name of the job.
            path: The root path to download the job artifact.

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
    def list_jobs(self, entity: str, project: str) -> list[dict[str, Any]]:
        """Return a list of jobs, if any, for the given entity and project.

        Args:
            entity: The entity for the listed jobs.
            project: The project for the listed jobs.

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
    def artifact_exists(self, name: str, type: str | None = None) -> bool:
        """Whether an artifact version exists within the specified project and entity.

        Args:
            name: The name of artifact. Add the artifact's entity and project
                as a prefix. Append the version or the alias of the artifact
                with a colon. If the entity or project is not specified,
                W&B uses override parameters if populated. Otherwise, the
                entity is pulled from the user settings and the project is
                set to "Uncategorized".
            type: The type of artifact.

        Returns:
            True if the artifact version exists, False otherwise.

        Examples:
        In the proceeding code snippets "entity", "project", "artifact",
        "version", and "alias" are placeholders for your W&B entity, name of
        the project the artifact is in, the name of the artifact, and
        artifact's version, respectively.

        ```python
        import wandb

        wandb.Api().artifact_exists("entity/project/artifact:version")
        wandb.Api().artifact_exists("entity/project/artifact:alias")
        ```

        """
        try:
            self._artifact(name, type)
        except wandb.errors.CommError as e:
            if isinstance(e.exc, requests.Timeout):
                raise
            return False
        return True

    @normalize_exceptions
    def artifact_collection_exists(self, name: str, type: str) -> bool:
        """Whether an artifact collection exists within a specified project and entity.

        Args:
            name: An artifact collection name. Optionally append the
                entity that logged the artifact as a prefix followed by
                a forward slash. If entity or project is not specified,
                infer the collection from the override params if they exist.
                Otherwise, entity is pulled from the user settings and project
                will default to "uncategorized".
            type: The type of artifact collection.

        Returns:
            True if the artifact collection exists, False otherwise.

        Examples:
        In the proceeding code snippet "type", and "collection_name" refer to the type
        of the artifact collection and the name of the collection, respectively.

        ```python
        import wandb

        wandb.Api.artifact_collection_exists(type="type", name="collection_name")
        ```
        """
        try:
            self.artifact_collection(type, name)
        except wandb.errors.CommError as e:
            if isinstance(e.exc, requests.Timeout):
                raise
            return False
        return True

    @tracked
    def registries(
        self,
        organization: str | None = None,
        filter: dict[str, Any] | None = None,
    ) -> Registries:
        """Returns a lazy iterator of `Registry` objects.

        Use the iterator to search and filter registries, collections,
        or artifact versions across your organization's registry.

        Args:
            organization: (str, optional) The organization of the registry to fetch.
                If not specified, use the organization specified in the user's settings.
            filter: (dict, optional) MongoDB-style filter to apply to each object in the lazy registry iterator.
                Fields available to filter for registries are
                    `name`, `description`, `created_at`, `updated_at`.
                Fields available to filter for collections are
                    `name`, `tag`, `description`, `created_at`, `updated_at`
                Fields available to filter for versions are
                    `tag`, `alias`, `created_at`, `updated_at`, `metadata`

        Returns:
            A lazy iterator of `Registry` objects.

        Examples:
        Find all registries with the names that contain "model"

        ```python
        import wandb

        api = wandb.Api()  # specify an org if your entity belongs to multiple orgs
        api.registries(filter={"name": {"$regex": "model"}})
        ```

        Find all collections in the registries with the name "my_collection" and the tag "my_tag"

        ```python
        api.registries().collections(filter={"name": "my_collection", "tag": "my_tag"})
        ```

        Find all artifact versions in the registries with a collection name that contains "my_collection" and a version that has the alias "best"

        ```python
        api.registries().collections(
            filter={"name": {"$regex": "my_collection"}}
        ).versions(filter={"alias": "best"})
        ```

        Find all artifact versions in the registries that contain "model" and have the tag "prod" or alias "best"

        ```python
        api.registries(filter={"name": {"$regex": "model"}}).versions(
            filter={"$or": [{"tag": "prod"}, {"alias": "best"}]}
        )
        ```
        """
        if not InternalApi()._server_supports(ServerFeature.ARTIFACT_REGISTRY_SEARCH):
            raise RuntimeError(
                "Registry search API is not enabled on this wandb server version. "
                "Please upgrade your server version or contact support at support@wandb.com."
            )

        organization = organization or fetch_org_from_settings_or_entity(
            self.settings, self.default_entity
        )
        return Registries(self.client, organization, filter)

    @tracked
    def registry(self, name: str, organization: str | None = None) -> Registry:
        """Return a registry given a registry name.

        Args:
            name: The name of the registry. This is without the `wandb-registry-`
                prefix.
            organization: The organization of the registry.
                If no organization is set in the settings, the organization will be
                fetched from the entity if the entity only belongs to one
                organization.

        Returns:
            A registry object.

        Examples:
        Fetch and update a registry

        ```python
        import wandb

        api = wandb.Api()
        registry = api.registry(name="my-registry", organization="my-org")
        registry.description = "This is an updated description"
        registry.save()
        ```
        """
        if not InternalApi()._server_supports(ServerFeature.ARTIFACT_REGISTRY_SEARCH):
            raise RuntimeError(
                "api.registry() is not enabled on this wandb server version. "
                "Please upgrade your server version or contact support at support@wandb.com."
            )
        organization = organization or fetch_org_from_settings_or_entity(
            self.settings, self.default_entity
        )
        org_entity = fetch_org_entity_from_organization(self.client, organization)
        registry = Registry(self.client, organization, org_entity, name)
        registry.load()
        return registry

    @tracked
    def create_registry(
        self,
        name: str,
        visibility: Literal["organization", "restricted"],
        organization: str | None = None,
        description: str | None = None,
        artifact_types: list[str] | None = None,
    ) -> Registry:
        """Create a new registry.

        Args:
            name: The name of the registry. Name must be unique within the organization.
            visibility: The visibility of the registry.
                organization: Anyone in the organization can view this registry. You can
                    edit their roles later from the settings in the UI.
                restricted: Only invited members via the UI can access this registry.
                    Public sharing is disabled.
            organization: The organization of the registry.
                If no organization is set in the settings, the organization will be
                fetched from the entity if the entity only belongs to one organization.
            description: The description of the registry.
            artifact_types: The accepted artifact types of the registry. A type is no
                more than 128 characters and do not include characters `/` or `:`. If
                not specified, all types are accepted.
                Allowed types added to the registry cannot be removed later.

        Returns:
            A registry object.

        Examples:
        ```python
        import wandb

        api = wandb.Api()
        registry = api.create_registry(
            name="my-registry",
            visibility="restricted",
            organization="my-org",
            description="This is a test registry",
            artifact_types=["model"],
        )
        ```
        """
        if not InternalApi()._server_supports(
            ServerFeature.INCLUDE_ARTIFACT_TYPES_IN_REGISTRY_CREATION
        ):
            raise RuntimeError(
                "create_registry api is not enabled on this wandb server version. "
                "Please upgrade your server version or contact support at support@wandb.com."
            )

        organization = organization or fetch_org_from_settings_or_entity(
            self.settings, self.default_entity
        )

        try:
            existing_registry = self.registry(name=name, organization=organization)
        except ValueError:
            existing_registry = None
        if existing_registry:
            raise ValueError(
                f"Registry {name!r} already exists in organization {organization!r},"
                " please use a different name."
            )

        return Registry.create(
            self.client,
            organization,
            name,
            visibility,
            description,
            artifact_types,
        )

    @tracked
    def integrations(
        self,
        entity: str | None = None,
        *,
        per_page: int = 50,
    ) -> Iterator[Integration]:
        """Return an iterator of all integrations for an entity.

        Args:
            entity: The entity (e.g. team name) for which to
                fetch integrations.  If not provided, the user's default entity
                will be used.
            per_page: Number of integrations to fetch per page.
                Defaults to 50.  Usually there is no reason to change this.

        Yields:
            Iterator[SlackIntegration | WebhookIntegration]: An iterator of any supported integrations.
        """
        from wandb.apis.public.integrations import Integrations

        params = {"entityName": entity or self.default_entity}
        return Integrations(client=self.client, variables=params, per_page=per_page)

    @tracked
    def webhook_integrations(
        self, entity: str | None = None, *, per_page: int = 50
    ) -> Iterator[WebhookIntegration]:
        """Returns an iterator of webhook integrations for an entity.

        Args:
            entity: The entity (e.g. team name) for which to
                fetch integrations.  If not provided, the user's default entity
                will be used.
            per_page: Number of integrations to fetch per page.
                Defaults to 50.  Usually there is no reason to change this.

        Yields:
            Iterator[WebhookIntegration]: An iterator of webhook integrations.

        Examples:
        Get all registered webhook integrations for the team "my-team":

        ```python
        import wandb

        api = wandb.Api()
        webhook_integrations = api.webhook_integrations(entity="my-team")
        ```

        Find only webhook integrations that post requests to "https://my-fake-url.com":

        ```python
        webhook_integrations = api.webhook_integrations(entity="my-team")
        my_webhooks = [
            ig
            for ig in webhook_integrations
            if ig.url_endpoint.startswith("https://my-fake-url.com")
        ]
        ```
        """
        from wandb.apis.public.integrations import WebhookIntegrations

        params = {"entityName": entity or self.default_entity}
        return WebhookIntegrations(
            client=self.client, variables=params, per_page=per_page
        )

    @tracked
    def slack_integrations(
        self, *, entity: str | None = None, per_page: int = 50
    ) -> Iterator[SlackIntegration]:
        """Returns an iterator of Slack integrations for an entity.

        Args:
            entity: The entity (e.g. team name) for which to
                fetch integrations.  If not provided, the user's default entity
                will be used.
            per_page: Number of integrations to fetch per page.
                Defaults to 50.  Usually there is no reason to change this.

        Yields:
            Iterator[SlackIntegration]: An iterator of Slack integrations.

        Examples:
        Get all registered Slack integrations for the team "my-team":

        ```python
        import wandb

        api = wandb.Api()
        slack_integrations = api.slack_integrations(entity="my-team")
        ```

        Find only Slack integrations that post to channel names starting with "team-alerts-":

        ```python
        slack_integrations = api.slack_integrations(entity="my-team")
        team_alert_integrations = [
            ig
            for ig in slack_integrations
            if ig.channel_name.startswith("team-alerts-")
        ]
        ```
        """
        from wandb.apis.public.integrations import SlackIntegrations

        params = {"entityName": entity or self.default_entity}
        return SlackIntegrations(
            client=self.client, variables=params, per_page=per_page
        )

    def _supports_automation(
        self,
        *,
        event: EventType | None = None,
        action: ActionType | None = None,
    ) -> bool:
        """Returns whether the server recognizes the automation event and/or action."""
        from wandb.automations._utils import (
            ALWAYS_SUPPORTED_ACTIONS,
            ALWAYS_SUPPORTED_EVENTS,
        )

        api = InternalApi()
        supports_event = (
            (event is None)
            or (event in ALWAYS_SUPPORTED_EVENTS)
            or api._server_supports(f"AUTOMATION_EVENT_{event.value}")
        )
        supports_action = (
            (action is None)
            or (action in ALWAYS_SUPPORTED_ACTIONS)
            or api._server_supports(f"AUTOMATION_ACTION_{action.value}")
        )
        return supports_event and supports_action

    def _omitted_automation_fragments(self) -> set[str]:
        """Returns the names of unsupported automation-related fragments.

        Older servers won't recognize newer GraphQL types, so a valid request may
        unnecessarily error out because it won't recognize fragments defined on those types.

        So e.g. if a server does not support `NO_OP` action types, then the following need to be
        removed from the body of the GraphQL request:

            - Fragment definition:
                ```
                fragment NoOpActionFields on NoOpTriggeredAction {
                    noOp
                }
                ```

            - Fragment spread in selection set:
                ```
                {
                    ...NoOpActionFields
                    # ... other fields ...
                }
                ```
        """
        from wandb.automations import ActionType
        from wandb.automations._generated import (
            GenericWebhookActionFields,
            NoOpActionFields,
            NotificationActionFields,
            QueueJobActionFields,
        )

        # Note: we can't currently define this as a constant outside the method
        # and still keep it nearby in this module, because it relies on pydantic v2-only imports
        fragment_names: dict[ActionType, str] = {
            ActionType.NO_OP: nameof(NoOpActionFields),
            ActionType.QUEUE_JOB: nameof(QueueJobActionFields),
            ActionType.NOTIFICATION: nameof(NotificationActionFields),
            ActionType.GENERIC_WEBHOOK: nameof(GenericWebhookActionFields),
        }

        return set(
            name
            for action in ActionType
            if (not self._supports_automation(action=action))
            and (name := fragment_names.get(action))
        )

    @tracked
    def automation(
        self,
        name: str,
        *,
        entity: str | None = None,
    ) -> Automation:
        """Returns the only Automation matching the parameters.

        Args:
            name: The name of the automation to fetch.
            entity: The entity to fetch the automation for.

        Raises:
            ValueError: If zero or multiple Automations match the search criteria.

        Examples:
        Get an existing automation named "my-automation":

        ```python
        import wandb

        api = wandb.Api()
        automation = api.automation(name="my-automation")
        ```

        Get an existing automation named "other-automation", from the entity "my-team":

        ```python
        automation = api.automation(name="other-automation", entity="my-team")
        ```
        """
        return one(
            self.automations(entity=entity, name=name),
            too_short=ValueError("No automations found"),
            too_long=ValueError("Multiple automations found"),
        )

    @tracked
    def automations(
        self,
        entity: str | None = None,
        *,
        name: str | None = None,
        per_page: int = 50,
    ) -> Iterator[Automation]:
        """Returns an iterator over all Automations that match the given parameters.

        If no parameters are provided, the returned iterator will contain all
        Automations that the user has access to.

        Args:
            entity: The entity to fetch the automations for.
            name: The name of the automation to fetch.
            per_page: The number of automations to fetch per page.
                Defaults to 50.  Usually there is no reason to change this.

        Returns:
            A list of automations.

        Examples:
        Fetch all existing automations for the entity "my-team":

        ```python
        import wandb

        api = wandb.Api()
        automations = api.automations(entity="my-team")
        ```
        """
        from wandb.apis.public.automations import Automations
        from wandb.automations._generated import (
            GET_AUTOMATIONS_BY_ENTITY_GQL,
            GET_AUTOMATIONS_GQL,
        )

        # For now, we need to use different queries depending on whether entity is given
        variables = {"entityName": entity}
        if entity is None:
            gql_str = GET_AUTOMATIONS_GQL  # Automations for viewer
        else:
            gql_str = GET_AUTOMATIONS_BY_ENTITY_GQL  # Automations for entity

        # If needed, rewrite the GraphQL field selection set to omit unsupported fields/fragments/types
        omit_fragments = self._omitted_automation_fragments()
        query = gql_compat(gql_str, omit_fragments=omit_fragments)
        iterator = Automations(
            client=self.client, variables=variables, per_page=per_page, _query=query
        )

        # FIXME: this is crude, move this client-side filtering logic into backend
        if name is not None:
            iterator = filter(lambda x: x.name == name, iterator)
        yield from iterator

    @normalize_exceptions
    @tracked
    def create_automation(
        self,
        obj: NewAutomation,
        *,
        fetch_existing: bool = False,
        **kwargs: Unpack[WriteAutomationsKwargs],
    ) -> Automation:
        """Create a new Automation.

        Args:
            obj:
                The automation to create.
            fetch_existing:
                If True, and a conflicting automation already exists, attempt
                to fetch the existing automation instead of raising an error.
            **kwargs:
                Any additional values to assign to the automation before
                creating it.  If given, these will override any values that may
                already be set on the automation:
                - `name`: The name of the automation.
                - `description`: The description of the automation.
                - `enabled`: Whether the automation is enabled.
                - `scope`: The scope of the automation.
                - `event`: The event that triggers the automation.
                - `action`: The action that is triggered by the automation.

        Returns:
            The saved Automation.

        Examples:
        Create a new automation named "my-automation" that sends a Slack notification
        when a run within a specific project logs a metric exceeding a custom threshold:

        ```python
        import wandb
        from wandb.automations import OnRunMetric, RunEvent, SendNotification

        api = wandb.Api()

        project = api.project("my-project", entity="my-team")

        # Use the first Slack integration for the team
        slack_hook = next(api.slack_integrations(entity="my-team"))

        event = OnRunMetric(
            scope=project,
            filter=RunEvent.metric("custom-metric") > 10,
        )
        action = SendNotification.from_integration(slack_hook)

        automation = api.create_automation(
            event >> action,
            name="my-automation",
            description="Send a Slack message whenever 'custom-metric' exceeds 10.",
        )
        ```
        """
        from wandb.automations import Automation
        from wandb.automations._generated import CREATE_AUTOMATION_GQL, CreateAutomation
        from wandb.automations._utils import prepare_to_create

        gql_input = prepare_to_create(obj, **kwargs)

        if not self._supports_automation(
            event=(event := gql_input.triggering_event_type),
            action=(action := gql_input.triggered_action_type),
        ):
            raise ValueError(
                f"Automation event or action ({event!r} -> {action!r}) "
                "is not supported on this wandb server version. "
                "Please upgrade your server version, or contact support at "
                "support@wandb.com."
            )

        # If needed, rewrite the GraphQL field selection set to omit unsupported fields/fragments/types
        omit_fragments = self._omitted_automation_fragments()
        mutation = gql_compat(CREATE_AUTOMATION_GQL, omit_fragments=omit_fragments)
        variables = {"params": gql_input.model_dump(exclude_none=True)}

        name = gql_input.name
        try:
            data = self.client.execute(mutation, variable_values=variables)
        except requests.HTTPError as e:
            status = HTTPStatus(e.response.status_code)
            if status is HTTPStatus.CONFLICT:  # 409
                if fetch_existing:
                    wandb.termlog(f"Automation {name!r} exists. Fetching it instead.")
                    return self.automation(name=name)

                raise ValueError(
                    f"Automation {name!r} exists. Unable to create another with the same name."
                ) from None
            raise

        try:
            result = CreateAutomation.model_validate(data).result
        except ValidationError as e:
            msg = f"Invalid response while creating automation {name!r}"
            raise RuntimeError(msg) from e

        if (result is None) or (result.trigger is None):
            msg = f"Empty response while creating automation {name!r}"
            raise RuntimeError(msg)

        return Automation.model_validate(result.trigger)

    @normalize_exceptions
    @tracked
    def update_automation(
        self,
        obj: Automation,
        *,
        create_missing: bool = False,
        **kwargs: Unpack[WriteAutomationsKwargs],
    ) -> Automation:
        """Update an existing automation.

        Args:
            obj: The automation to update.  Must be an existing automation.
            create_missing (bool):
                If True, and the automation does not exist, create it.
            **kwargs:
                Any additional values to assign to the automation before
                updating it.  If given, these will override any values that may
                already be set on the automation:
                - `name`: The name of the automation.
                - `description`: The description of the automation.
                - `enabled`: Whether the automation is enabled.
                - `scope`: The scope of the automation.
                - `event`: The event that triggers the automation.
                - `action`: The action that is triggered by the automation.

        Returns:
            The updated automation.

        Examples:
        Disable and edit the description of an existing automation ("my-automation"):

        ```python
        import wandb

        api = wandb.Api()

        automation = api.automation(name="my-automation")
        automation.enabled = False
        automation.description = "Kept for reference, but no longer used."

        updated_automation = api.update_automation(automation)
        ```

        OR

        ```python
        import wandb

        api = wandb.Api()

        automation = api.automation(name="my-automation")

        updated_automation = api.update_automation(
            automation,
            enabled=False,
            description="Kept for reference, but no longer used.",
        )
        ```
        """
        from wandb.automations import ActionType, Automation
        from wandb.automations._generated import UPDATE_AUTOMATION_GQL, UpdateAutomation
        from wandb.automations._utils import prepare_to_update

        # Check if the server even supports updating automations.
        #
        # NOTE: Unfortunately, there is no current server feature flag for this.  As a workaround,
        # we check whether the server supports the NO_OP action, which is a reasonably safe proxy
        # for whether it supports updating automations.
        if not self._supports_automation(action=ActionType.NO_OP):
            raise RuntimeError(
                "Updating existing automations is not enabled on this wandb server version. "
                "Please upgrade your server version, or contact support at support@wandb.com."
            )

        gql_input = prepare_to_update(obj, **kwargs)

        if not self._supports_automation(
            event=(event := gql_input.triggering_event_type),
            action=(action := gql_input.triggered_action_type),
        ):
            raise ValueError(
                f"Automation event or action ({event.value} -> {action.value}) "
                "is not supported on this wandb server version. "
                "Please upgrade your server version, or contact support at "
                "support@wandb.com."
            )

        # If needed, rewrite the GraphQL field selection set to omit unsupported fields/fragments/types
        omit_fragments = self._omitted_automation_fragments()
        mutation = gql_compat(UPDATE_AUTOMATION_GQL, omit_fragments=omit_fragments)
        variables = {"params": gql_input.model_dump(exclude_none=True)}

        name = gql_input.name
        try:
            data = self.client.execute(mutation, variable_values=variables)
        except requests.HTTPError as e:
            status = HTTPStatus(e.response.status_code)
            if status is HTTPStatus.NOT_FOUND:  # 404
                if create_missing:
                    wandb.termlog(f"Automation {name!r} not found. Creating it.")
                    return self.create_automation(obj)

                raise ValueError(
                    f"Automation {name!r} not found. Unable to edit it."
                ) from e

            # Not a (known) recoverable HTTP error
            wandb.termerror(f"Got response status {status!r}: {e.response.text!r}")
            raise

        try:
            result = UpdateAutomation.model_validate(data).result
        except ValidationError as e:
            msg = f"Invalid response while updating automation {name!r}"
            raise RuntimeError(msg) from e

        if (result is None) or (result.trigger is None):
            msg = f"Empty response while updating automation {name!r}"
            raise RuntimeError(msg)

        return Automation.model_validate(result.trigger)

    @normalize_exceptions
    @tracked
    def delete_automation(self, obj: Automation | str) -> Literal[True]:
        """Delete an automation.

        Args:
            obj: The automation to delete, or its ID.

        Returns:
            True if the automation was deleted successfully.
        """
        from wandb.automations._generated import DELETE_AUTOMATION_GQL, DeleteAutomation
        from wandb.automations._utils import extract_id

        id_ = extract_id(obj)
        mutation = gql(DELETE_AUTOMATION_GQL)
        variables = {"id": id_}

        data = self.client.execute(mutation, variable_values=variables)

        try:
            result = DeleteAutomation.model_validate(data).result
        except ValidationError as e:
            msg = f"Invalid response while deleting automation {id_!r}"
            raise RuntimeError(msg) from e

        if result is None:
            msg = f"Empty response while deleting automation {id_!r}"
            raise RuntimeError(msg)

        if not result.success:
            raise RuntimeError(f"Failed to delete automation: {id_!r}")

        return result.success
