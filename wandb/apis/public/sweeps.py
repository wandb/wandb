"""W&B Public API for Sweeps.

This module provides classes for interacting with W&B hyperparameter
optimization sweeps.

Example:
```python
from wandb.apis.public import Api

# Get a specific sweep
sweep = Api().sweep("entity/project/sweep_id")

# Access sweep properties
print(f"Sweep: {sweep.name}")
print(f"State: {sweep.state}")
print(f"Best Loss: {sweep.best_loss}")

# Get best performing run
best_run = sweep.best_run()
print(f"Best Run: {best_run.name}")
print(f"Metrics: {best_run.summary}")
```

Note:
    This module is part of the W&B Public API and provides read-only access
    to sweep data. For creating and controlling sweeps, use the wandb.sweep()
    and wandb.agent() functions from the main wandb package.
"""

from __future__ import annotations

import json
import logging
import urllib
from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from typing_extensions import override

import wandb
from wandb import env, util
from wandb.apis import public
from wandb.apis.attrs import Attrs
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import SizedPaginator
from wandb.errors import Error, UnsupportedError, UsageError
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.lib import ipython
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

# Minimum W&B server release that supports filtering sweeps via the `filters`
# argument on the `sweeps` field.
_SWEEP_FILTERS_MIN_SERVER_VERSION = "0.81.4"

logger = logging.getLogger(__name__)

SweepState = Literal["RUNNING", "PAUSED", "CANCELED", "FINISHED"]

if TYPE_CHECKING:
    from wandb.apis._generated import GetSweeps
    from wandb.apis.public.api import Api
    from wandb.apis.public.runs import AgentRuns
    from wandb.apis.public.service_api import ServiceApi


class Sweeps(SizedPaginator["Sweep"]):
    """A lazy iterator over a collection of `Sweep` objects.

    Examples:
    ```python
    from wandb.apis.public import Api

    sweeps = Api().project(name="project_name", entity="entity").sweeps()

    # Iterate over sweeps and print details
    for sweep in sweeps:
        print(f"Sweep name: {sweep.name}")
        print(f"Sweep ID: {sweep.id}")
        print(f"Sweep URL: {sweep.url}")
        print("----------")
    ```
    """

    QUERY: ClassVar[str | None] = None
    last_response: GetSweeps | None

    def __init__(
        self,
        service_api: ServiceApi,
        entity: str,
        project: str,
        per_page: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> None:
        """An iterable collection of `Sweep` objects.

        Args:
            service_api: The service API used to query W&B.
            entity: The entity which owns the sweeps.
            project: The project which contains the sweeps.
            per_page: The number of sweeps to fetch per request to the API.
            filters: (dict) queries for specific sweeps using the runs filters,
                See wandb/apis/public/api.py:runs for more details.
        """
        if self.QUERY is None:
            from wandb.apis._generated import GET_SWEEPS_GQL

            type(self).QUERY = GET_SWEEPS_GQL

        self.entity = entity
        self.project = project
        self._service_api = service_api
        self._supports_filtering = service_api.feature_enabled(
            pb.SWEEPS_QUERY_FILTERING
        )

        # Fail fast if the caller requested filtering but the
        # server can't honor it, rather than silently returning unfiltered sweeps.
        if filters and not self._supports_filtering:
            raise UnsupportedError(
                "Filtering sweeps is not supported on this W&B server version. "
                "Please upgrade your server to release "
                f"{_SWEEP_FILTERS_MIN_SERVER_VERSION} or later, or query sweeps "
                "on https://wandb.ai."
            )

        variables = {
            "project": self.project,
            "entity": self.entity,
            "filters": json.dumps(filters or {}),
        }
        super().__init__(service_api, variables, per_page)

    @override
    def _update_response(self) -> None:
        """Fetch and validate the response data for the current page."""
        from wandb.apis._generated import GetSweeps

        # On servers that don't support the `filters` argument, strip it from the
        # query so that listing sweeps still works.
        omit_variables = None if self._supports_filtering else ["filters"]
        self.last_response = self._service_api.execute_graphql(
            self.QUERY,
            variables=self.variables,
            omit_variables=omit_variables,
            parse=GetSweeps.model_validate_json,
        )

    @property
    @override
    def _length(self) -> int:
        """The total number of sweeps in the project.

        <!-- lazydoc-ignore -->
        """
        if not self.last_response:
            self._load_page()

        if not self.last_response or not self.last_response.project:
            return 0

        return self.last_response.project.total_sweeps

    @property
    @override
    def more(self) -> bool:
        """Returns whether there are more sweeps to fetch.

        <!-- lazydoc-ignore -->
        """
        if (
            self.last_response
            and self.last_response.project
            and self.last_response.project.sweeps
            and self.last_response.project.sweeps.page_info
        ):
            return self.last_response.project.sweeps.page_info.has_next_page

        return True

    @property
    @override
    def cursor(self) -> str | None:
        """Returns the cursor for the next page of sweeps.

        <!-- lazydoc-ignore -->
        """
        if (
            self.last_response
            and self.last_response.project
            and self.last_response.project.sweeps
            and self.last_response.project.sweeps.page_info
        ):
            return self.last_response.project.sweeps.page_info.end_cursor

        return None

    @override
    def convert_objects(self) -> list[Sweep]:
        """Converts the last GraphQL response into a list of `Sweep` objects.

        <!-- lazydoc-ignore -->
        """
        from wandb._pydantic import Connection
        from wandb.apis._generated import SweepFragment

        if (rsp := self.last_response) is None or (project := rsp.project) is None:
            msg = f"Could not find project {self.project!r}"
            raise ValueError(msg)

        if project.total_sweeps < 1:
            return []
        return [
            Sweep(
                self._service_api,
                self.entity,
                self.project,
                node.name,
            )
            for node in Connection[SweepFragment].model_validate(project.sweeps).nodes()
        ]

    def __repr__(self):
        return f"<Sweeps {self.entity}/{self.project}>"


def _get_sweep(
    service_api: ServiceApi,
    entity: str | None = None,
    project: str | None = None,
    sid: str | None = None,
    order: str | None = None,
    query: str | None = None,
    **kwargs: Any,
) -> Sweep | None:
    """Fetch a sweep using an already-owned service API."""
    from wandb.apis._generated import GET_SWEEP_GQL, GET_SWEEP_LEGACY_GQL

    if not order:
        order = "+created_at"

    variables = {"entity": entity, "project": project, "name": sid, **kwargs}
    if query is None:
        query = GET_SWEEP_GQL
    try:
        data = service_api.execute_graphql(query, variables=variables)
    except Exception:
        # Don't handle exception, rely on legacy query
        # TODO(gst): Implement updated introspection workaround
        query = GET_SWEEP_LEGACY_GQL
        data = service_api.execute_graphql(query, variables=variables)

    # FIXME: looks like this method allows passing arbitrary GQL queries, so for now
    # we'll have to skip trying to validate the result with a generated pydantic model.
    if not (
        data
        and (proj_dict := data.get("project"))
        and (sweep_dict := proj_dict.get("sweep"))
    ):
        return None
    sweep = Sweep(
        service_api,
        entity,
        project,
        sid,
        attrs=sweep_dict,
    )
    sweep.runs = public.Runs(
        service_api,
        entity,
        project,
        order=order,
        per_page=10,
        filters={"$and": [{"sweep": sweep.id}]},
    )
    return sweep


class Sweep(Attrs):
    """The set of runs associated with the sweep.

    Attributes:
        runs (Runs): List of runs
        id (str): Sweep ID
        project (str): The name of the project the sweep belongs to
        config (dict): Dictionary containing the sweep configuration
        state (str): The state of the sweep. Can be "Finished", "Failed",
            "Crashed", or "Running".
        expected_run_count (int): The number of expected runs for the sweep
    """

    def __init__(
        self,
        service_api: ServiceApi,
        entity: str,
        project: str,
        sweep_id: str,
        attrs: Mapping[str, Any] | None = None,
    ):
        # TODO: Add agents / flesh this out.
        super().__init__(dict(attrs or {}))
        self._entity = entity
        self.project = project
        self.id = sweep_id
        self._service_api = service_api
        self.runs = []

        self.load(force=not attrs)

    @property
    def entity(self) -> str:
        """The entity associated with the sweep."""
        return self._entity

    @property
    def username(self) -> str:
        """Deprecated. Use `Sweep.entity` instead."""
        wandb.termwarn("Sweep.username is deprecated. please use Sweep.entity instead.")
        return self._entity

    @property
    def config(self):
        """The sweep configuration used for the sweep."""
        return util.load_yaml(self._attrs["config"])

    def load(self, force: bool = False):
        """Fetch and update sweep data logged to the run from GraphQL database.

        <!-- lazydoc-ignore -->
        """
        if force or not self._attrs:
            if not (
                sweep := _get_sweep(
                    self._service_api,
                    self.entity,
                    self.project,
                    self.id,
                )
            ):
                raise ValueError(f"Could not find sweep {self!r}")
            self._attrs = sweep._attrs
            self.runs = sweep.runs

        return self._attrs

    @property
    def order(self):
        """Return the order key for the sweep."""
        if self._attrs.get("config") and self.config.get("metric"):
            sort_order = self.config["metric"].get("goal", "minimize")
            prefix = "+" if sort_order == "minimize" else "-"
            return public.QueryGenerator.format_order_key(
                prefix + self.config["metric"]["name"]
            )

    def best_run(self, order=None):
        """Return the best run sorted by the metric defined in config or the order passed in."""
        if order is None:
            order = self.order
        else:
            order = public.QueryGenerator.format_order_key(order)
        if order is None:
            wandb.termwarn(
                "No order specified and couldn't find metric in sweep config, returning most recent run"
            )
        else:
            wandb.termlog("Sorting runs by {}".format(order))
        filters = {"$and": [{"sweep": self.id}]}
        try:
            return public.Runs(
                self._service_api,
                self.entity,
                self.project,
                order=order,
                filters=filters,
                per_page=1,
            )[0]
        except IndexError:
            return None

    @property
    def expected_run_count(self) -> int | None:
        """Return the number of expected runs in the sweep or None for infinite runs."""
        return self._attrs.get("runCountExpected")

    @property
    def path(self):
        """Returns the path of the project.

        The path is a list containing the entity, project name, and sweep ID."""
        return [
            urllib.parse.quote_plus(self.entity),
            urllib.parse.quote_plus(self.project),
            urllib.parse.quote_plus(self.id),
        ]

    @property
    def url(self):
        """The URL of the sweep.

        The sweep URL is generated from the entity, project, the term
        "sweeps", and the sweep ID.run_id. For
        SaaS users, it takes the form
        of `https://wandb.ai/entity/project/sweeps/sweeps_ID`.
        """
        path = self.path
        path.insert(2, "sweeps")
        return self._service_api.app_url + "/".join(path)

    @property
    def name(self):
        """The name of the sweep.

        Returns the first name that exists in the following priority order:

        1. User-edited display name
        2. Name configured at creation time
        3. Sweep ID
        """
        return self._attrs.get("displayName") or self.config.get("name") or self.id

    @classmethod
    def get(
        cls,
        api: Api,
        entity: str | None = None,
        project: str | None = None,
        sid: str | None = None,
        order: str | None = None,
        query: str | None = None,
        **kwargs,
    ):
        """Execute a query against the cloud backend.

        Args:
            api: The W&B API instance.
            entity: The entity (username or team) that owns the project.
            project: The name of the project to fetch sweep from.
            sid: The sweep ID to query.
            order: The order in which the sweep's runs are returned.
            query: The query to use to execute the query.
            **kwargs: Additional keyword arguments to pass to the query.
        """
        return api._get_sweep(
            entity,
            project,
            sid,
            order=order,
            query=query,
            **kwargs,
        )

    def _make_sweep_agent(self, attrs: Mapping[str, Any]) -> Agent:
        """Construct `Agent` from API payload."""
        try:
            return Agent(
                self._service_api,
                attrs=attrs,
                entity=self.entity,
                project=self.project,
                sweep_id=self.id,
            )
        except ValueError as e:
            raise Error(
                "Sweep agent data from the W&B API was incomplete or invalid.",
                context={"details": str(e)},
            ) from e

    def agent(self, agent_id: str) -> Agent:
        """Query an agent by ID for this sweep.

        Args:
            agent_id: The ID of the agent to look up.
        """
        from wandb.apis._generated import GET_SWEEP_AGENT_GQL

        variables = {
            "agentID": agent_id,
            "sweep": self.id,
            "entity": self.entity,
            "project": self.project,
        }
        data = self._service_api.execute_graphql(
            GET_SWEEP_AGENT_GQL,
            variables=variables,
        )
        return self._make_sweep_agent(data["project"]["sweep"]["agent"])

    def agents(self) -> list[Agent]:
        """Query the list of all agents for this sweep."""
        from wandb.apis._generated import GET_SWEEP_AGENTS_GQL, GetSweepAgents

        variables = {
            "sweep": self.id,
            "entity": self.entity,
            "project": self.project,
        }
        parsed = self._service_api.execute_graphql(
            GET_SWEEP_AGENTS_GQL,
            variables=variables,
            parse=GetSweepAgents.model_validate_json,
        )
        if not parsed.project or not parsed.project.sweep:
            return []
        return [
            self._make_sweep_agent(edge.node.model_dump(by_alias=True))
            for edge in parsed.project.sweep.agents.edges
        ]

    def enqueue_run(self, config: dict, display_name: str | None = None) -> str:
        """Enqueue a run for the sweep.

        Args:
            config: The config for the run.
            display_name: The optional display name for the run.

        Returns:
            The id of the run (not the run queue item).

        Raises:
            UnsupportedError: If the server doesn't support enqueuing sweep runs.
        """
        if not self._service_api.feature_enabled(
            pb.ServerFeature.SWEEPS_LOCAL_SCHEDULER
        ):
            raise UnsupportedError(
                "Enqueuing sweep runs is not supported on this wandb server "
                "version. Please upgrade your server version or contact "
                "support at support@wandb.com."
            )

        mutation = """
        mutation EnqueueSweepRun(
            $id: ID!,
            $config: JSONString!,
            $displayName: String,
        ) {
            enqueueSweepRun(input: {
                id: $id,
                config: $config,
                displayName: $displayName,
            }) {
                id
                runQueueItemId
            }
        }
        """
        data = self._service_api.execute_graphql(
            mutation,
            variables={
                "id": self._attrs["id"],
                "config": json.dumps(config),
                "displayName": display_name,
            },
        )
        return data["enqueueSweepRun"]["id"]

    def to_html(self, height: int = 420, hidden: bool = False) -> str:
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

    def __repr__(self) -> str:
        pathstr = "/".join(self.path)
        state = self._attrs.get("state", "Unknown State")
        return f"<Sweep {pathstr} ({state})>"


class Agent(Attrs):
    def __init__(
        self,
        service_api: ServiceApi,
        attrs: Mapping[str, Any],
        entity: str,
        project: str,
        sweep_id: str,
    ) -> None:
        super().__init__(dict(attrs or {}))
        self._entity = entity
        self._project = project
        self._sweep_id = sweep_id
        self._service_api = service_api

        if self._entity is None:
            raise ValueError(
                "Agent requires entity. "
                "Use an Agent returned from sweep.agent(...) or sweep.agents()."
            )
        if self._project is None:
            raise ValueError(
                "Agent requires project. "
                "Use an Agent returned from sweep.agent(...) or sweep.agents()."
            )
        if self._sweep_id is None:
            raise ValueError(
                "Agent requires sweep_id. "
                "Use an Agent returned from sweep.agent(...) or sweep.agents()."
            )
        if not (self._attrs.get("name") or self._attrs.get("id")):
            if self._attrs.get("name") is None:
                raise ValueError("Agent is missing name.")
            if self._attrs.get("id") is None:
                raise ValueError("Agent is missing id.")
            raise ValueError("Agent is missing a usable name or id.")
        self._agent_key: str = self._attrs.get("name") or self._attrs.get("id")

    def runs(
        self,
        per_page: int = 50,
    ) -> AgentRuns:
        """Return a paginated collection of runs executed by this agent."""
        from wandb.apis.public.runs import AgentRuns

        total_runs = int(self._attrs.get("totalRuns") or 0)
        return AgentRuns(
            self._service_api,
            entity=self._entity,
            project=self._project,
            sweep_id=self._sweep_id,
            agent_key=self._agent_key,
            total_runs=total_runs,
            order="+created_at",
            per_page=per_page,
        )

    def __repr__(self) -> str:
        state = self._attrs.get("state", "Unknown State")
        name = self._attrs.get("id", "Unknown")
        return f"<Agent {name} ({state})>"


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
            if isinstance(parameter["min"], int) and isinstance(parameter["max"], int):
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
def _upsert_sweep(
    api: Api,
    config: dict,
    *,
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
) -> tuple[dict[str, Any], list[str]]:
    """Create or update a sweep.

    Returns the sweep as the server returned it and the config validation
    warnings. The sweep's project and entity become the process defaults so
    that agents started afterwards in the same process find the sweep.
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

    config = _validate_config_and_fill_distribution(config)

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

    config_str = yaml.dump(json.loads(json.dumps(config)), Dumper=NonOctalStringDumper)
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
                "entityName": entity or api.settings["entity"],
                "projectName": project or api.settings["project"],
                "controller": controller,
                "launchScheduler": launch_scheduler,
                "templateVariableValues": json.dumps(template_variable_values),
                "scheduler": scheduler,
                "priorRunsFilters": filters,
                "displayName": display_name,
            }
            if state:
                variables["state"] = state

            response = api._service_api.execute_graphql(mutation, variables=variables)
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

    sweep: dict[str, Any] = response["upsertSweep"]["sweep"]
    if project_obj := sweep.get("project"):
        env.set_project(project_obj["name"])
        if entity_obj := project_obj.get("entity"):
            env.set_entity(entity_obj["name"])

    return sweep, response["upsertSweep"].get("configValidationWarnings", [])


@normalize_exceptions
def _sweep_with_runs(
    api: Api,
    sweep: str,
    specs: str,
    *,
    project: str | None = None,
    entity: str | None = None,
) -> dict[str, Any]:
    """Fetch a sweep with its runs and their sampled history.

    Args:
        sweep: The sweep to get details for.
        specs: History specs.
        project: The project to scope this sweep to.
        entity: The entity to scope this sweep to.
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
    entity = entity or api.settings["entity"]
    project = project or api.settings["project"]
    response = api._service_api.execute_graphql(
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
        data["runs"] = [edge["node"] for edge in data["runs"]["edges"]]
    return data


@normalize_exceptions
def _register_agent(
    api: Api,
    host: str,
    *,
    sweep_id: str,
    project: str | None = None,
    entity: str | None = None,
) -> dict[str, Any]:
    """Register a new sweep agent and return it."""
    mutation = """
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
    response = api._service_api.execute_graphql(
        mutation,
        variables={
            "host": host,
            "entityName": entity or api.settings["entity"],
            "projectName": project or api.settings["project"],
            "sweep": sweep_id,
        },
    )
    return response["createAgent"]["agent"]


def _agent_heartbeat(
    api: Api, agent_id: str, metrics: dict, run_states: dict
) -> list[dict[str, Any]]:
    """Notify the server about agent state and receive commands to execute.

    Raises:
        SweepNotFoundError: If the server returns a 404, indicating the
            sweep was likely deleted.
    """
    from wandb.sdk.sweeps import SweepNotFoundError

    mutation = """
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

    if agent_id is None:
        raise ValueError("Cannot call heartbeat with an unregistered agent.")

    try:
        response = api._service_api.execute_graphql(
            mutation,
            variables={
                "id": agent_id,
                "metrics": json.dumps(metrics),
                "runState": json.dumps(run_states),
            },
            timeout=60,
        )
    except WandbApiFailedError as e:
        if e.response is not None and e.response.http_status == 404:
            raise SweepNotFoundError(
                "Sweep not found. The sweep may have been deleted."
            ) from e
        logger.exception("Error communicating with W&B.")
        return []
    except Exception:
        logger.exception("Error communicating with W&B.")
        return []
    return json.loads(response["agentHeartbeat"]["commands"])


def _get_sweep_state(
    api: Api, sweep: str, *, entity: str | None = None, project: str | None = None
) -> SweepState:
    query = """
        query GetSweepState($entity: String, $project: String, $sweep: String!) {
            project(name: $project, entityName: $entity) {
                sweep(sweepName: $sweep) {
                    state
                }
            }
        }
        """
    response = api._service_api.execute_graphql(
        query,
        variables={
            "sweep": sweep,
            "entity": entity or api.settings["entity"],
            "project": project or api.settings["project"],
        },
    )
    return response["project"]["sweep"]["state"]


def _set_sweep_state(
    api: Api,
    sweep: str,
    state: SweepState,
    *,
    entity: str | None = None,
    project: str | None = None,
) -> None:
    assert state in ("RUNNING", "PAUSED", "CANCELED", "FINISHED")
    s = _sweep_with_runs(api, sweep, "{}", entity=entity, project=project)
    curr_state = s["state"].upper()
    if state == "PAUSED" and curr_state not in ("PAUSED", "RUNNING"):
        raise Exception(f"Cannot pause {curr_state.lower()} sweep.")
    elif state != "RUNNING" and curr_state not in ("RUNNING", "PAUSED", "PENDING"):
        raise Exception(f"Sweep already {curr_state.lower()}.")
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
    api._service_api.execute_graphql(
        mutation,
        variables={
            "id": s["id"],
            "state": state,
            "entityName": entity or api.settings["entity"],
            "projectName": project or api.settings["project"],
        },
    )
