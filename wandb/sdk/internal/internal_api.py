from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, overload

import wandb
from wandb import env
from wandb.analytics import TelemetryRecorder, get_telemetry_recorder
from wandb.apis.normalize import normalize_exceptions
from wandb.errors import AuthenticationError, UsageError
from wandb.integration.sagemaker import parse_sm_secrets
from wandb.sdk import wandb_setup

from ..lib import wbauth

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from typing import TypedDict

    from wandb.apis.public.service_api import ServiceApi

    class DefaultSettings(TypedDict, total=False):
        section: str
        git_remote: str
        ignore_globs: list[str]
        base_url: str
        root_dir: str | None
        api_key: str | None
        entity: str | None
        organization: str | None
        project: str | None
        _extra_http_headers: Mapping[str, str] | None
        _proxies: Mapping[str, str] | None

    _Response = MutableMapping
    SweepState = Literal["RUNNING", "PAUSED", "CANCELED", "FINISHED"]


class Api:
    """W&B Internal Api wrapper.

    Note:
        Settings are automatically overridden by looking for
        a `wandb/settings` file in the current working directory or its parent
        directory. If none can be found, we look in the current user's home
        directory.

    Args:
        default_settings(dict, optional): If you aren't using a settings
        file, or you wish to override the section to use in the settings file
        Override the settings here.
    """

    HTTP_TIMEOUT = env.get_http_timeout(20)

    def __init__(
        self,
        default_settings: (
            wandb.Settings  #
            | DefaultSettings
            | None
        ) = None,
        load_settings: bool = True,
        environ: MutableMapping[str, str] = os.environ,
        api_key: str | None = None,
        telemetry_recorder: TelemetryRecorder | None = None,
    ) -> None:
        self._environ = environ

        default_overrides: dict[str, Any] = (
            dict(default_settings) if default_settings else {}
        )
        self.default_settings: DefaultSettings = {
            "section": default_overrides.get("section", "default"),
            "git_remote": default_overrides.get("git_remote", "origin"),
            "ignore_globs": default_overrides.get("ignore_globs", []),
            "base_url": default_overrides.get("base_url", "https://api.wandb.ai"),
            "root_dir": default_overrides.get("root_dir"),
            "api_key": default_overrides.get("api_key"),
            "entity": default_overrides.get("entity"),
            "organization": default_overrides.get("organization"),
            "project": default_overrides.get("project"),
            "_extra_http_headers": default_overrides.get("_extra_http_headers"),
            "_proxies": default_overrides.get("_proxies"),
        }

        if load_settings:
            global_settings = wandb_setup.singleton().settings
            if root_dir := self.default_settings["root_dir"]:
                global_settings = global_settings.model_copy()
                global_settings.root_dir = root_dir

            self._settings = global_settings.read_system_settings().all()
        else:
            self._settings = {}

        # todo: remove these hacky hacks after settings refactor is complete
        #  keeping this code here to limit scope and so that it is easy to remove later
        self._extra_http_headers = self.settings("_extra_http_headers") or json.loads(
            self._environ.get("WANDB__EXTRA_HTTP_HEADERS", "{}")
        )

        auth: tuple[str, str] | None = None
        api_key = api_key or self.default_settings.get("api_key")
        session_auth = wbauth.session_credentials(host=self.api_url)
        if api_key:
            # Credentials provided explicitly for this instance.
            auth = ("api", api_key)
        elif isinstance(session_auth, wbauth.AuthApiKey):
            # Credentials configured for the session, such as through
            # wandb.login().
            auth = ("api", session_auth.api_key)
        elif isinstance(session_auth, wbauth.AuthIdentityTokenFile):
            # Federated identity: wandb-core exchanges the identity token
            # for an access token and authenticates its requests with it.
            # Code that talks to the server directly gets the token from
            # wandb-core through the access_token property.
            pass
        elif token_file := self._environ.get(env.IDENTITY_TOKEN_FILE):
            # Federated identity configured in the environment, before
            # session credentials are established.
            if not Path(token_file).exists():
                raise AuthenticationError(
                    f"Identity token file not found: {token_file}"
                )
        else:
            auth = ("api", self.api_key or "")

        proxies = self.settings("_proxies") or json.loads(
            self._environ.get("WANDB__PROXIES", "{}")
        )

        self._request_auth = auth
        request_headers = {
            "User-Agent": self.user_agent,
            "X-WANDB-USERNAME": env.get_username(env=self._environ),
            "X-WANDB-USER-EMAIL": env.get_user_email(env=self._environ),
            **self._extra_http_headers,
        }
        self._request_headers = {
            key: value for key, value in request_headers.items() if value is not None
        }
        self._request_proxies = dict(proxies or {})
        self._service_api = self._new_service_api()
        self._telemetry_recorder = telemetry_recorder or get_telemetry_recorder()

    def relocate(self) -> None:
        """Ensure the current api points to the right server."""
        self._service_api = self._new_service_api()

    def execute(self, *args: Any, **kwargs: Any) -> _Response:
        return self._service_api.execute_graphql(*args, **kwargs)  # type: ignore[return-value]

    @property
    def request_auth(self) -> tuple[str, str] | None:
        return self._request_auth

    def _new_service_api(self) -> ServiceApi:
        from wandb.apis.public.service_api import ServiceApi

        settings = wandb_setup.singleton().settings.model_copy()
        settings.base_url = self.settings("base_url")
        settings.api_key = self._request_auth[1] if self._request_auth else ""
        if settings.api_key:
            # wandb-core prefers an identity token file over an API key,
            # so clear any token file inherited from the global settings.
            settings.identity_token_file = None
        settings.x_extra_http_headers = dict(self._request_headers)
        settings.x_graphql_timeout_seconds = self.HTTP_TIMEOUT

        if http_proxy := self._request_proxies.get("http"):
            settings.http_proxy = http_proxy
        if https_proxy := self._request_proxies.get("https"):
            settings.https_proxy = https_proxy

        return ServiceApi(
            settings=settings,
            timeout=self.HTTP_TIMEOUT,
        )

    @property
    def user_agent(self) -> str:
        return f"W&B Internal Client {wandb.__version__}"

    @property
    def api_key(self) -> str | None:
        if (  #
            (auth := wbauth.session_credentials(host=self.api_url))
            and isinstance(auth, wbauth.AuthApiKey)
        ):
            return auth.api_key

        return (
            os.getenv(env.API_KEY)
            or wbauth.read_netrc_auth(host=self.api_url)
            or parse_sm_secrets().get(env.API_KEY)
            or self.default_settings.get("api_key")
        )

    @property
    def is_authenticated(self) -> bool:
        return self.api_key is not None or self._service_api.access_token() is not None

    @property
    def api_url(self) -> str:
        return self.settings("base_url")  # type: ignore

    @overload
    def settings(self, key: None = None) -> dict[str, Any]: ...

    @overload
    def settings(self, key: str) -> Any: ...

    def settings(self, key: str | None = None) -> Any:
        """The settings overridden from the wandb/settings file.

        Args:
            key (str, optional): If provided only this setting is returned
            section (str, optional): If provided this section of the setting file is
            used, defaults to "default"

        Returns:
            A dict with the current settings

                {
                    "entity": "models",
                    "base_url": "https://api.wandb.ai",
                    "project": None,
                    "organization": "my-org",
                }
        """
        result: dict[str, Any] = dict(self.default_settings)
        result.update(self._settings)
        result.update(
            {
                "entity": env.get_entity(
                    self._settings.get(
                        "entity",
                        result.get("entity"),
                    ),
                    env=self._environ,
                ),
                "organization": env.get_organization(
                    self._settings.get(
                        "organization",
                        result.get("organization"),
                    ),
                    env=self._environ,
                ),
                "project": env.get_project(
                    self._settings.get(
                        "project",
                        result.get("project"),
                    ),
                    env=self._environ,
                ),
                "base_url": env.get_base_url(
                    self._settings.get(
                        "base_url",
                        result.get("base_url"),
                    ),
                    env=self._environ,
                ),
            }
        )

        return result if key is None else result[key]

    def set_setting(self, key: str, value: Any) -> None:
        self._settings[key] = value

        if key == "entity":
            env.set_entity(value, env=self._environ)
        elif key == "project":
            env.set_project(value, env=self._environ)
        elif key == "base_url":
            self.relocate()

    @normalize_exceptions
    def sweep(
        self,
        sweep: str,
        specs: str,
        project: str | None = None,
        entity: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve sweep.

        Args:
            sweep (str): The sweep to get details for
            specs (str): history specs
            project (str, optional): The project to scope this sweep to.
            entity (str, optional): The entity to scope this sweep to.

        Returns:
                [{"id","name","repo","dockerImage","description"}]
        """
        query = """
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
        entity = entity or self.settings("entity")
        project = project or self.settings("project")
        response = self.execute(
            query,
            variables={
                "entity": entity,
                "project": project,
                "sweep": sweep,
                "specs": specs,
            },
        )
        if response["project"] is None or response["project"]["sweep"] is None:
            raise ValueError(f"Sweep {entity}/{project}/{sweep} not found")
        data: dict[str, Any] = response["project"]["sweep"]
        if data:
            data["runs"] = self._flatten_edges(data["runs"])
        return data

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
            # still shows an anaconda warning, but doesn't error
            return config

        for parameter_name in config["parameters"]:
            parameter = config["parameters"][parameter_name]
            if (
                "min" in parameter
                and "max" in parameter
                and "distribution" not in parameter
            ):
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
                        f"Parameter {parameter_name} is ambiguous, please specify bounds as both floats (for a float_"
                        "uniform distribution) or ints (for an int_uniform distribution)."
                    )
        return config

    @normalize_exceptions
    def upsert_sweep(
        self,
        config: dict,
        controller: str | None = None,
        launch_scheduler: str | None = None,
        scheduler: str | None = None,
        obj_id: str | None = None,
        project: str | None = None,
        entity: str | None = None,
        state: str | None = None,
        prior_runs: list[str] | None = None,
        display_name: str | None = None,
        template_variable_values: dict[str, Any] | None = None,
    ) -> tuple[str, list[str]]:
        """Upsert a sweep object.

        Args:
            config (dict): sweep config (will be converted to yaml)
            controller (str): controller to use
            launch_scheduler (str): launch scheduler to use
            scheduler (str): scheduler to use
            obj_id (str): object id
            project (str): project to use
            entity (str): entity to use
            state (str): state
            prior_runs (list): IDs of existing runs to add to the sweep
            display_name (str): display name for the sweep
            template_variable_values (dict): template variable values
        """
        import yaml

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
            $state: String,
            $priorRunsFilters: JSONString,
            $displayName: String,
        ) {
            upsertSweep(input: {
                id: $id,
                config: $config,
                description: $description,
                entityName: $entityName,
                projectName: $projectName,
                controller: $controller,
                scheduler: $scheduler,
                state: $state,
                priorRunsFilters: $priorRunsFilters,
                displayName: $displayName,
            }) {
                sweep {
                    name
                    _PROJECT_QUERY_
                }
                configValidationWarnings
            }
        }
        """
        # TODO(jhr): we need protocol versioning to know schema is not supported
        # for now we will just try both new and old query
        mutation_5 = (
            mutation_str.replace(
                "$controller: JSONString,",
                "$controller: JSONString,$launchScheduler: JSONString, $templateVariableValues: JSONString,",
            )
            .replace(
                "controller: $controller,",
                "controller: $controller,launchScheduler: $launchScheduler,templateVariableValues: $templateVariableValues,",
            )
            .replace("_PROJECT_QUERY_", project_query)
        )
        # launchScheduler was introduced in core v0.14.0
        mutation_4 = (
            mutation_str.replace(
                "$controller: JSONString,",
                "$controller: JSONString,$launchScheduler: JSONString,",
            )
            .replace(
                "controller: $controller,",
                "controller: $controller,launchScheduler: $launchScheduler",
            )
            .replace("_PROJECT_QUERY_", project_query)
        )

        # mutation 3 maps to backend that can support CLI version of at least 0.10.31
        mutation_3 = mutation_str.replace("_PROJECT_QUERY_", project_query)
        mutation_2 = mutation_str.replace("_PROJECT_QUERY_", project_query).replace(
            "configValidationWarnings", ""
        )
        mutation_1 = mutation_str.replace("_PROJECT_QUERY_", "").replace(
            "configValidationWarnings", ""
        )

        # TODO(dag): replace this with a query for protocol versioning
        mutations = [mutation_5, mutation_4]
        if launch_scheduler is None:
            mutations.extend([mutation_3, mutation_2, mutation_1])

        config = self._validate_config_and_fill_distribution(config)

        # Silly, but attr-dicts like Easydicts don't serialize correctly to yaml.
        # This sanitizes them with a round trip pass through json to get a regular dict.
        class NonOctalStringDumper(yaml.Dumper):
            """Prevents strings containing non-octal values like "008" and "009" from being converted to numbers in in the yaml string saved as the sweep config."""

            def represent_scalar(self, tag, value, style=None):
                if (
                    tag == "tag:yaml.org,2002:str"
                    and value.startswith("0")
                    and len(value) > 1
                ):
                    return super().represent_scalar(tag, value, style="'")
                return super().represent_scalar(tag, value, style)

        config_str = yaml.dump(
            json.loads(json.dumps(config)), Dumper=NonOctalStringDumper
        )
        filters = None
        if prior_runs:
            filters = json.dumps({"$or": [{"name": r} for r in prior_runs]})

        err: Exception | None = None
        for mutation in mutations:
            try:
                variables = {
                    "id": obj_id,
                    "config": config_str,
                    "description": config.get("description"),
                    "entityName": entity or self.settings("entity"),
                    "projectName": project or self.settings("project"),
                    "controller": controller,
                    "launchScheduler": launch_scheduler,
                    "templateVariableValues": json.dumps(template_variable_values),
                    "scheduler": scheduler,
                    "priorRunsFilters": filters,
                    "displayName": display_name,
                }
                if state:
                    variables["state"] = state

                response = self.execute(
                    mutation,
                    variables=variables,
                )
            except UsageError:
                raise
            except Exception as e:
                # graphql schema exception is generic
                err = e
                continue
            err = None
            break
        if err:
            raise err

        sweep: dict[str, dict[str, dict]] = response["upsertSweep"]["sweep"]
        project_obj: dict[str, dict] = sweep.get("project", {})
        if project_obj:
            self.set_setting("project", project_obj["name"])
            entity_obj: dict = project_obj.get("entity", {})
            if entity_obj:
                self.set_setting("entity", entity_obj["name"])

        warnings = response["upsertSweep"].get("configValidationWarnings", [])
        return response["upsertSweep"]["sweep"]["name"], warnings

    def set_sweep_state(
        self,
        sweep: str,
        state: SweepState,
        entity: str | None = None,
        project: str | None = None,
    ) -> None:
        assert state in ("RUNNING", "PAUSED", "CANCELED", "FINISHED")
        s = self.sweep(sweep=sweep, entity=entity, project=project, specs="{}")
        curr_state = s["state"].upper()
        if state == "PAUSED" and curr_state not in ("PAUSED", "RUNNING"):
            raise Exception(f"Cannot pause {curr_state.lower()} sweep.")
        elif state != "RUNNING" and curr_state not in ("RUNNING", "PAUSED", "PENDING"):
            raise Exception(f"Sweep already {curr_state.lower()}.")
        sweep_id = s["id"]
        mutation = """
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
        self.execute(
            mutation,
            variables={
                "id": sweep_id,
                "state": state,
                "entityName": entity or self.settings("entity"),
                "projectName": project or self.settings("project"),
            },
        )

    def _flatten_edges(self, response: _Response) -> list[dict]:
        """Return an array from the nested graphql relay structure."""
        return [node["node"] for node in response["edges"]]
