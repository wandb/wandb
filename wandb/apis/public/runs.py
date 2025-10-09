"""W&B Public API for Runs.

This module provides classes for interacting with W&B runs and their associated
data.

Example:
```python
from wandb.apis.public import Api

# Get runs matching filters
runs = Api().runs(
    path="entity/project", filters={"state": "finished", "config.batch_size": 32}
)

# Access run data
for run in runs:
    print(f"Run: {run.name}")
    print(f"Config: {run.config}")
    print(f"Metrics: {run.summary}")

    # Get history with pandas
    history_df = run.history(keys=["loss", "accuracy"], pandas=True)

    # Work with artifacts
    for artifact in run.logged_artifacts():
        print(f"Artifact: {artifact.name}")
```

Note:
    This module is part of the W&B Public API and provides read/write access
    to run data. For logging new runs, use the wandb.init() function from
    the main wandb package.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib
from typing import TYPE_CHECKING, Any, Collection, Literal, Mapping

from wandb_gql import gql

import wandb
from wandb import env, util
from wandb.apis import public
from wandb.apis.attrs import Attrs
from wandb.apis.internal import Api as InternalApi
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import SizedPaginator
from wandb.apis.public.const import RETRY_TIMEDELTA
from wandb.sdk.lib import ipython, json_util, runid
from wandb.sdk.lib.paths import LogicalPath

if TYPE_CHECKING:
    from wandb.apis.public import RetryingClient

WANDB_INTERNAL_KEYS = {"_wandb", "wandb_version"}

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

# Lightweight fragment for listing operations - excludes heavy fields
LIGHTWEIGHT_RUN_FRAGMENT = """fragment LightweightRunFragment on Run {
    id
    tags
    name
    displayName
    sweepName
    state
    group
    jobType
    commit
    readOnly
    createdAt
    heartbeatAt
    description
    notes
    historyLineCount
    user {
        name
        username
    }
}"""

# Fragment name constants to avoid string parsing
RUN_FRAGMENT_NAME = "RunFragment"
LIGHTWEIGHT_RUN_FRAGMENT_NAME = "LightweightRunFragment"


def _create_runs_query(
    *, lazy: bool, with_internal_id: bool, with_project_id: bool
) -> gql:
    """Create GraphQL query for runs with appropriate fragment."""
    fragment = LIGHTWEIGHT_RUN_FRAGMENT if lazy else RUN_FRAGMENT
    fragment_name = LIGHTWEIGHT_RUN_FRAGMENT_NAME if lazy else RUN_FRAGMENT_NAME

    return gql(
        f"""#graphql
        query Runs($project: String!, $entity: String!, $cursor: String, $perPage: Int = 50, $order: String, $filters: JSONString) {{
            project(name: $project, entityName: $entity) {{
                {"internalId" if with_internal_id else ""}
                runCount(filters: $filters)
                readOnly
                runs(filters: $filters, after: $cursor, first: $perPage, order: $order) {{
                    edges {{
                        node {{
                            {"projectId" if with_project_id else ""}
                            ...{fragment_name}
                        }}
                        cursor
                    }}
                    pageInfo {{
                        endCursor
                        hasNextPage
                    }}
                }}
            }}
        }}
        {fragment}
        """
    )


@normalize_exceptions
def _server_provides_internal_id_for_project(client) -> bool:
    """Returns True if the server allows us to query the internalId field for a project."""
    query_string = """
       query ProbeProjectInput {
            ProjectType: __type(name:"Project") {
                fields {
                    name
                }
            }
        }
    """

    # Only perform the query once to avoid extra network calls
    query = gql(query_string)
    res = client.execute(query)
    return "internalId" in [
        x["name"] for x in (res.get("ProjectType", {}).get("fields", [{}]))
    ]


@normalize_exceptions
def _server_provides_project_id_for_run(client) -> bool:
    """Returns True if the server allows us to query the projectId field for a run."""
    query_string = """
       query ProbeRunInput {
            RunType: __type(name:"Run") {
                fields {
                    name
                }
            }
        }
    """

    # Only perform the query once to avoid extra network calls
    query = gql(query_string)
    res = client.execute(query)
    return "projectId" in [
        x["name"] for x in (res.get("RunType", {}).get("fields", [{}]))
    ]


@normalize_exceptions
def _convert_to_dict(value: Any) -> dict[str, Any]:
    """Converts a value to a dictionary.

    If the value is already a dictionary, the value is returned unchanged.
    If the value is a string, bytes, or bytearray, it is parsed as JSON.
    For any other type, a TypeError is raised.
    """
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except json.decoder.JSONDecodeError:
            # ignore invalid utf-8 or control characters
            return json.loads(value, strict=False)

    raise TypeError(f"Unable to convert {value} to a dict")


class Runs(SizedPaginator["Run"]):
    """A lazy iterator of `Run` objects associated with a project and optional filter.

    Runs are retrieved in pages from the W&B server as needed.

    This is generally used indirectly using the `Api.runs` namespace.

    Args:
        client: (`wandb.apis.public.RetryingClient`) The API client to use
            for requests.
        entity: (str) The entity (username or team) that owns the project.
        project: (str) The name of the project to fetch runs from.
        filters: (Optional[Dict[str, Any]]) A dictionary of filters to apply
            to the runs query.
        order: (str) Order can be `created_at`, `heartbeat_at`, `config.*.value`, or `summary_metrics.*`.
            If you prepend order with a + order is ascending (default).
            If you prepend order with a - order is descending.
            The default order is run.created_at from oldest to newest.
        per_page: (int) The number of runs to fetch per request (default is 50).
        include_sweeps: (bool) Whether to include sweep information in the
            runs. Defaults to True.

    Examples:
    ```python
    from wandb.apis.public.runs import Runs
    from wandb.apis.public import Api

    # Get all runs from a project that satisfy the filters
    filters = {"state": "finished", "config.optimizer": "adam"}

    runs = Api().runs(
        client=api.client,
        entity="entity",
        project="project_name",
        filters=filters,
    )

    # Iterate over runs and print details
    for run in runs:
        print(f"Run name: {run.name}")
        print(f"Run ID: {run.id}")
        print(f"Run URL: {run.url}")
        print(f"Run state: {run.state}")
        print(f"Run config: {run.config}")
        print(f"Run summary: {run.summary}")
        print(f"Run history (samples=5): {run.history(samples=5)}")
        print("----------")

    # Get histories for all runs with specific metrics
    histories_df = runs.histories(
        samples=100,  # Number of samples per run
        keys=["loss", "accuracy"],  # Metrics to fetch
        x_axis="_step",  # X-axis metric
        format="pandas",  # Return as pandas DataFrame
    )
    ```
    """

    def __init__(
        self,
        client: RetryingClient,
        entity: str,
        project: str,
        filters: dict[str, Any] | None = None,
        order: str = "+created_at",
        per_page: int = 50,
        include_sweeps: bool = True,
        lazy: bool = True,
    ):
        if not order:
            order = "+created_at"

        self.QUERY = _create_runs_query(
            lazy=lazy,
            with_internal_id=_server_provides_internal_id_for_project(client),
            with_project_id=_server_provides_project_id_for_run(client),
        )

        self.entity = entity
        self.project = project
        self._project_internal_id = None
        self.filters = filters or {}
        self.order = order
        self._sweeps = {}
        self._include_sweeps = include_sweeps
        self._lazy = lazy
        variables = {
            "project": self.project,
            "entity": self.entity,
            "order": self.order,
            "filters": json.dumps(self.filters),
        }
        super().__init__(client, variables, per_page)

    @property
    def _length(self):
        """Returns the total number of runs.

        <!-- lazydoc-ignore: internal -->
        """
        if not self.last_response:
            self._load_page()
        return self.last_response["project"]["runCount"]

    @property
    def more(self) -> bool:
        """Returns whether there are more runs to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return bool(
                self.last_response["project"]["runs"]["pageInfo"]["hasNextPage"]
            )
        else:
            return True

    @property
    def cursor(self):
        """Returns the cursor position for pagination of runs results.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return self.last_response["project"]["runs"]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self):
        """Converts GraphQL edges to Runs objects.

        <!-- lazydoc-ignore: internal -->
        """
        objs = []
        if self.last_response is None or self.last_response.get("project") is None:
            raise ValueError("Could not find project {}".format(self.project))
        for run_response in self.last_response["project"]["runs"]["edges"]:
            run = Run(
                self.client,
                self.entity,
                self.project,
                run_response["node"]["name"],
                run_response["node"],
                include_sweeps=self._include_sweeps,
                lazy=self._lazy,
            )
            objs.append(run)

            if self._include_sweeps and run.sweep_name:
                if run.sweep_name in self._sweeps:
                    sweep = self._sweeps[run.sweep_name]
                else:
                    sweep = public.Sweep.get(
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

    @normalize_exceptions
    def histories(
        self,
        samples: int = 500,
        keys: list[str] | None = None,
        x_axis: str = "_step",
        format: Literal["default", "pandas", "polars"] = "default",
        stream: Literal["default", "system"] = "default",
    ):
        """Return sampled history metrics for all runs that fit the filters conditions.

        Args:
            samples: The number of samples to return per run
            keys: Only return metrics for specific keys
            x_axis: Use this metric as the xAxis defaults to _step
            format: Format to return data in, options are "default", "pandas",
                "polars"
            stream: "default" for metrics, "system" for machine metrics
        Returns:
            pandas.DataFrame: If `format="pandas"`, returns a `pandas.DataFrame`
                of history metrics.
            polars.DataFrame: If `format="polars"`, returns a `polars.DataFrame`
                of history metrics.
            list of dicts: If `format="default"`, returns a list of dicts
                containing history metrics with a `run_id` key.
        """
        if format not in ("default", "pandas", "polars"):
            raise ValueError(
                f"Invalid format: {format}. Must be one of 'default', 'pandas', 'polars'"
            )

        histories = []

        if format == "default":
            for run in self:
                history_data = run.history(
                    samples=samples,
                    keys=keys,
                    x_axis=x_axis,
                    pandas=False,
                    stream=stream,
                )
                if not history_data:
                    continue
                for entry in history_data:
                    entry["run_id"] = run.id
                histories.extend(history_data)

            return histories

        if format == "pandas":
            pd = util.get_module(
                "pandas", required="Exporting pandas DataFrame requires pandas"
            )
            for run in self:
                history_data = run.history(
                    samples=samples,
                    keys=keys,
                    x_axis=x_axis,
                    pandas=False,
                    stream=stream,
                )
                if not history_data:
                    continue
                df = pd.DataFrame.from_records(history_data)
                df["run_id"] = run.id
                histories.append(df)
            if not histories:
                return pd.DataFrame()
            combined_df = pd.concat(histories)
            combined_df.reset_index(drop=True, inplace=True)
            # sort columns for consistency
            combined_df = combined_df[(sorted(combined_df.columns))]

            return combined_df

        if format == "polars":
            pl = util.get_module(
                "polars", required="Exporting polars DataFrame requires polars"
            )
            for run in self:
                history_data = run.history(
                    samples=samples,
                    keys=keys,
                    x_axis=x_axis,
                    pandas=False,
                    stream=stream,
                )
                if not history_data:
                    continue
                df = pl.from_records(history_data)
                df = df.with_columns(pl.lit(run.id).alias("run_id"))
                histories.append(df)
            if not histories:
                return pl.DataFrame()
            combined_df = pl.concat(histories, how="vertical")
            # sort columns for consistency
            combined_df = combined_df.select(sorted(combined_df.columns))

            return combined_df

    def __repr__(self):
        return f"<Runs {self.entity}/{self.project}>"

    def upgrade_to_full(self):
        """Upgrade this Runs collection from lazy to full mode.

        This switches to fetching full run data and
        upgrades any already-loaded Run objects to have full data.
        Uses parallel loading for better performance when upgrading multiple runs.
        """
        if not self._lazy:
            return  # Already in full mode

        # Switch to full mode
        self._lazy = False

        # Regenerate query with full fragment
        self.QUERY = _create_runs_query(
            lazy=False,
            with_internal_id=_server_provides_internal_id_for_project(self.client),
            with_project_id=_server_provides_project_id_for_run(self.client),
        )

        # Upgrade any existing runs that have been loaded - use parallel loading for performance
        lazy_runs = [run for run in self.objects if run._lazy]
        if lazy_runs:
            from concurrent.futures import ThreadPoolExecutor

            # Limit workers to avoid overwhelming the server
            max_workers = min(len(lazy_runs), 10)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(run.load_full_data) for run in lazy_runs]
                # Wait for all to complete
                for future in futures:
                    future.result()


class Run(Attrs):
    """A single run associated with an entity and project.

    Args:
        client: The W&B API client.
        entity: The entity associated with the run.
        project: The project associated with the run.
        run_id: The unique identifier for the run.
        attrs: The attributes of the run.
        include_sweeps: Whether to include sweeps in the run.

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
        project_internal_id (int): the internal id of the project
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
        client: RetryingClient,
        entity: str,
        project: str,
        run_id: str,
        attrs: Mapping | None = None,
        include_sweeps: bool = True,
        lazy: bool = True,
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
        self._lazy = lazy
        self._full_data_loaded = False  # Track if we've loaded full data
        self.dir = os.path.join(self._base_dir, *self.path)
        try:
            os.makedirs(self.dir)
        except OSError:
            pass
        self._summary = None
        self._metadata: dict[str, Any] | None = None
        self._state = _attrs.get("state", "not found")
        self.server_provides_internal_id_field: bool | None = None
        self._server_provides_project_id_field: bool | None = None
        self._is_loaded: bool = False

        self.load(force=not _attrs)

    @property
    def state(self):
        """The state of the run. Can be one of: Finished, Failed, Crashed, or Running."""
        return self._state

    @property
    def entity(self):
        """The entity associated with the run."""
        return self._entity

    @property
    def username(self):
        """This API is deprecated. Use `entity` instead."""
        wandb.termwarn("Run.username is deprecated. Please use Run.entity instead.")
        return self._entity

    @property
    def storage_id(self):
        """The unique storage identifier for the run."""
        # For compatibility with wandb.Run, which has storage IDs
        # in self.storage_id and names in self.id.

        return self._attrs.get("id")

    @property
    def id(self):
        """The unique identifier for the run."""
        return self._attrs.get("name")

    @id.setter
    def id(self, new_id):
        """Set the unique identifier for the run."""
        attrs = self._attrs
        attrs["name"] = new_id
        return new_id

    @property
    def name(self):
        """The name of the run."""
        return self._attrs.get("displayName")

    @name.setter
    def name(self, new_name):
        """Set the name of the run."""
        self._attrs["displayName"] = new_name
        return new_name

    @classmethod
    def create(
        cls,
        api: public.Api,
        run_id: str | None = None,
        project: str | None = None,
        entity: str | None = None,
        state: Literal["running", "pending"] = "running",
    ):
        """Create a run for the given project."""
        api._sentry.message("Invoking Run.create", level="info")
        run_id = run_id or runid.generate_id()
        project = project or api.settings.get("project") or "uncategorized"
        mutation = gql(
            """
        mutation UpsertBucket($project: String, $entity: String, $name: String!, $state: String) {
            upsertBucket(input: {modelName: $project, entityName: $entity, name: $name, state: $state}) {
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
        variables = {
            "entity": entity,
            "project": project,
            "name": run_id,
            "state": state,
        }
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
                "state": state,
            },
            lazy=False,  # Created runs should have full data available immediately
        )

    def _load_with_fragment(
        self, fragment: str, fragment_name: str, force: bool = False
    ):
        """Load run data using specified GraphQL fragment."""
        # Cache the server capability check to avoid repeated network calls
        if self._server_provides_project_id_field is None:
            self._server_provides_project_id_field = (
                _server_provides_project_id_for_run(self.client)
            )

        query = gql(
            f"""
        query Run($project: String!, $entity: String!, $name: String!) {{
            project(name: $project, entityName: $entity) {{
                run(name: $name) {{
                    {"projectId" if self._server_provides_project_id_field else ""}
                    ...{fragment_name}
                }}
            }}
        }}
        {fragment}
        """
        )

        if force or not self._attrs:
            response = self._exec(query)
            if (
                response is None
                or response.get("project") is None
                or response["project"].get("run") is None
            ):
                raise ValueError("Could not find run {}".format(self))
            self._attrs = response["project"]["run"]

            self._state = self._attrs["state"]
            if self._attrs.get("user"):
                self.user = public.User(self.client, self._attrs["user"])

            if self._include_sweeps and self.sweep_name and not self.sweep:
                # There may be a lot of runs. Don't bother pulling them all
                # just for the sake of this one.
                self.sweep = public.Sweep.get(
                    self.client,
                    self.entity,
                    self.project,
                    self.sweep_name,
                    withRuns=False,
                )

        if not self._is_loaded:
            # Always set _project_internal_id if projectId is available, regardless of fragment type
            if "projectId" in self._attrs:
                self._project_internal_id = int(self._attrs["projectId"])
            else:
                self._project_internal_id = None

            # Only call _load_from_attrs when using the full fragment or when the fields are actually present
            if fragment_name == RUN_FRAGMENT_NAME or (
                "config" in self._attrs
                or "summaryMetrics" in self._attrs
                or "systemMetrics" in self._attrs
            ):
                self._load_from_attrs()
            self._is_loaded = True

        return self._attrs

    def _load_from_attrs(self):
        self._state = self._attrs.get("state", None)

        # Only convert fields if they exist in _attrs
        if "config" in self._attrs:
            self._attrs["config"] = _convert_to_dict(self._attrs.get("config"))
        if "summaryMetrics" in self._attrs:
            self._attrs["summaryMetrics"] = _convert_to_dict(
                self._attrs.get("summaryMetrics")
            )
        if "systemMetrics" in self._attrs:
            self._attrs["systemMetrics"] = _convert_to_dict(
                self._attrs.get("systemMetrics")
            )

        # Only check for sweeps if sweep_name is available (not in lazy mode or if it exists)
        if self._include_sweeps and self._attrs.get("sweepName") and not self.sweep:
            # There may be a lot of runs. Don't bother pulling them all
            self.sweep = public.Sweep(
                self.client,
                self.entity,
                self.project,
                self._attrs["sweepName"],
                withRuns=False,
            )

        config_user, config_raw = {}, {}
        if self._attrs.get("config"):
            try:
                # config is already converted to dict by _convert_to_dict
                for key, value in self._attrs.get("config", {}).items():
                    config = config_raw if key in WANDB_INTERNAL_KEYS else config_user
                    if isinstance(value, dict) and "value" in value:
                        config[key] = value["value"]
                    else:
                        config[key] = value
            except (TypeError, AttributeError):
                # Handle case where config is malformed or not a dict
                pass

        config_raw.update(config_user)
        self._attrs["config"] = config_user
        self._attrs["rawconfig"] = config_raw

        return self._attrs

    def load(self, force=False):
        """Load run data using appropriate fragment based on lazy mode."""
        if self._lazy:
            return self._load_with_fragment(
                LIGHTWEIGHT_RUN_FRAGMENT, LIGHTWEIGHT_RUN_FRAGMENT_NAME, force
            )
        else:
            return self._load_with_fragment(RUN_FRAGMENT, RUN_FRAGMENT_NAME, force)

    @normalize_exceptions
    def wait_until_finished(self):
        """Check the state of the run until it is finished."""
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
                self._attrs["state"] = state
                self._state = state
                return
            time.sleep(5)

    @normalize_exceptions
    def update(self):
        """Persist changes to the run object to the wandb backend."""
        mutation = gql(
            """
        mutation UpsertBucket($id: String!, $description: String, $display_name: String, $notes: String, $tags: [String!], $config: JSONString!, $groupName: String, $jobType: String) {{
            upsertBucket(input: {{id: $id, description: $description, displayName: $display_name, notes: $notes, tags: $tags, config: $config, groupName: $groupName, jobType: $jobType}}) {{
                bucket {{
                    ...RunFragment
                }}
            }}
        }}
        {}
        """.format(RUN_FRAGMENT)
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
            jobType=self.job_type,
        )
        self.summary.update()

    @normalize_exceptions
    def delete(self, delete_artifacts=False):
        """Delete the given run from the wandb backend.

        Args:
            delete_artifacts (bool, optional): Whether to delete the artifacts
                associated with the run.
        """
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
        """Persist changes to the run object to the W&B backend."""
        self.update()

    @property
    def json_config(self):
        """Return the run config as a JSON string.

        <!-- lazydoc-ignore: internal -->
        """
        config = {}
        if "_wandb" in self.rawconfig:
            config["_wandb"] = {"value": self.rawconfig["_wandb"], "desc": None}
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
        query RunFullHistory($project: String!, $entity: String!, $name: String!, $samples: Int) {{
            project(name: $project, entityName: $entity) {{
                run(name: $name) {{ {}(samples: $samples) }}
            }}
        }}
        """.format(node)
        )

        response = self._exec(query, samples=samples)
        return [json.loads(line) for line in response["project"]["run"][node]]

    @normalize_exceptions
    def files(
        self,
        names: list[str] | None = None,
        pattern: str | None = None,
        per_page: int = 50,
    ):
        """Returns a `Files` object for all files in the run which match the given criteria.

        You can specify a list of exact file names to match, or a pattern to match against.
        If both are provided, the pattern will be ignored.

        Args:
            names (list): names of the requested files, if empty returns all files
            pattern (str, optional): Pattern to match when returning files from W&B.
                This pattern uses mySQL's LIKE syntax,
                so matching all files that end with .json would be "%.json".
                If both names and pattern are provided, a ValueError will be raised.
            per_page (int): number of results per page.

        Returns:
            A `Files` object, which is an iterator over `File` objects.
        """
        return public.Files(
            self.client,
            self,
            names or [],
            pattern=pattern,
            per_page=per_page,
        )

    @normalize_exceptions
    def file(self, name):
        """Return the path of a file with a given name in the artifact.

        Args:
            name (str): name of requested file.

        Returns:
            A `File` matching the name argument.
        """
        return public.Files(self.client, self, [name])[0]

    @normalize_exceptions
    def upload_file(self, path, root="."):
        """Upload a local file to W&B, associating it with this run.

        Args:
            path (str): Path to the file to upload. Can be absolute or relative.
            root (str): The root path to save the file relative to. For example,
                if you want to have the file saved in the run as "my_dir/file.txt"
                and you're currently in "my_dir" you would set root to "../".
                Defaults to current directory (".").

        Returns:
            A `File` object representing the uploaded file.
        """
        api = InternalApi(
            default_settings={"entity": self.entity, "project": self.project},
            retry_timedelta=RETRY_TIMEDELTA,
        )
        api.set_current_run_id(self.id)
        root = os.path.abspath(root)
        name = os.path.relpath(path, root)
        upload_path = util.make_file_path_upload_safe(name)
        with open(os.path.join(root, name), "rb") as f:
            api.push({LogicalPath(upload_path): f})
        return public.Files(self.client, self, [name])[0]

    @normalize_exceptions
    def history(
        self, samples=500, keys=None, x_axis="_step", pandas=True, stream="default"
    ):
        """Return sampled history metrics for a run.

        This is simpler and faster if you are ok with the history records being sampled.

        Args:
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
            pd = util.get_module("pandas")
            if pd:
                lines = pd.DataFrame.from_records(lines)
            else:
                wandb.termwarn("Unable to load pandas, call history with pandas=False")
        return lines

    @normalize_exceptions
    def scan_history(self, keys=None, page_size=1000, min_step=None, max_step=None):
        """Returns an iterable collection of all history records for a run.

        Args:
            keys ([str], optional): only fetch these keys, and only fetch rows that have all of keys defined.
            page_size (int, optional): size of pages to fetch from the api.
            min_step (int, optional): the minimum number of pages to scan at a time.
            max_step (int, optional): the maximum number of pages to scan at a time.

        Returns:
            An iterable collection over history records (dict).

        Example:
        Export all the loss values for an example run

        ```python
        run = api.run("entity/project-name/run-id")
        history = run.scan_history(keys=["Loss"])
        losses = [row["Loss"] for row in history]
        ```
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
            return public.HistoryScan(
                run=self,
                client=self.client,
                page_size=page_size,
                min_step=min_step,
                max_step=max_step,
            )
        else:
            return public.SampledHistoryScan(
                run=self,
                client=self.client,
                keys=keys,
                page_size=page_size,
                min_step=min_step,
                max_step=max_step,
            )

    @normalize_exceptions
    def logged_artifacts(self, per_page: int = 100) -> public.RunArtifacts:
        """Fetches all artifacts logged by this run.

        Retrieves all output artifacts that were logged during the run. Returns a
        paginated result that can be iterated over or collected into a single list.

        Args:
            per_page: Number of artifacts to fetch per API request.

        Returns:
            An iterable collection of all Artifact objects logged as outputs during this run.

        Example:
        ```python
        import wandb
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
            tmp.write("This is a test artifact")
            tmp_path = tmp.name
        run = wandb.init(project="artifact-example")
        artifact = wandb.Artifact("test_artifact", type="dataset")
        artifact.add_file(tmp_path)
        run.log_artifact(artifact)
        run.finish()

        api = wandb.Api()

        finished_run = api.run(f"{run.entity}/{run.project}/{run.id}")

        for logged_artifact in finished_run.logged_artifacts():
            print(logged_artifact.name)
        ```

        """
        return public.RunArtifacts(self.client, self, mode="logged", per_page=per_page)

    @normalize_exceptions
    def used_artifacts(self, per_page: int = 100) -> public.RunArtifacts:
        """Fetches artifacts explicitly used by this run.

        Retrieves only the input artifacts that were explicitly declared as used
        during the run, typically via `run.use_artifact()`. Returns a paginated
        result that can be iterated over or collected into a single list.

        Args:
            per_page: Number of artifacts to fetch per API request.

        Returns:
            An iterable collection of Artifact objects explicitly used as inputs in this run.

        Example:
        ```python
        import wandb

        run = wandb.init(project="artifact-example")
        run.use_artifact("test_artifact:latest")
        run.finish()

        api = wandb.Api()
        finished_run = api.run(f"{run.entity}/{run.project}/{run.id}")
        for used_artifact in finished_run.used_artifacts():
            print(used_artifact.name)
        test_artifact
        ```
        """
        return public.RunArtifacts(self.client, self, mode="used", per_page=per_page)

    @normalize_exceptions
    def use_artifact(self, artifact, use_as=None):
        """Declare an artifact as an input to a run.

        Args:
            artifact (`Artifact`): An artifact returned from
                `wandb.Api().artifact(name)`
            use_as (string, optional): A string identifying
                how the artifact is used in the script. Used
                to easily differentiate artifacts used in a
                run, when using the beta wandb launch
                feature's artifact swapping functionality.

        Returns:
            An `Artifact` object.
        """
        api = InternalApi(
            default_settings={"entity": self.entity, "project": self.project},
            retry_timedelta=RETRY_TIMEDELTA,
        )
        api.set_current_run_id(self.id)

        if isinstance(artifact, wandb.Artifact) and not artifact.is_draft():
            api.use_artifact(
                artifact.id,
                use_as=use_as or artifact.name,
                artifact_entity_name=artifact.entity,
                artifact_project_name=artifact.project,
            )
            return artifact
        elif isinstance(artifact, wandb.Artifact) and artifact.is_draft():
            raise ValueError(
                "Only existing artifacts are accepted by this api. "
                "Manually create one with `wandb artifact put`"
            )
        else:
            raise ValueError("You must pass a wandb.Api().artifact() to use_artifact")

    @normalize_exceptions
    def log_artifact(
        self,
        artifact: wandb.Artifact,
        aliases: Collection[str] | None = None,
        tags: Collection[str] | None = None,
    ):
        """Declare an artifact as output of a run.

        Args:
            artifact (`Artifact`): An artifact returned from
                `wandb.Api().artifact(name)`.
            aliases (list, optional): Aliases to apply to this artifact.
            tags: (list, optional) Tags to apply to this artifact, if any.

        Returns:
            A `Artifact` object.
        """
        api = InternalApi(
            default_settings={"entity": self.entity, "project": self.project},
            retry_timedelta=RETRY_TIMEDELTA,
        )
        api.set_current_run_id(self.id)

        if not isinstance(artifact, wandb.Artifact):
            raise TypeError("You must pass a wandb.Api().artifact() to use_artifact")
        if artifact.is_draft():
            raise ValueError(
                "Only existing artifacts are accepted by this api. "
                "Manually create one with `wandb artifact put`"
            )
        if (
            self.entity != artifact.source_entity
            or self.project != artifact.source_project
        ):
            raise ValueError("A run can't log an artifact to a different project.")

        artifact_collection_name = artifact.source_name.split(":")[0]
        api.create_artifact(
            artifact.type,
            artifact_collection_name,
            artifact.digest,
            aliases=aliases,
            tags=tags,
        )
        return artifact

    def load_full_data(self, force: bool = False) -> dict[str, Any]:
        """Load full run data including heavy fields like config, systemMetrics, summaryMetrics.

        This method is useful when you initially used lazy=True for listing runs,
        but need access to the full data for specific runs.

        Args:
            force: Force reload even if data is already loaded

        Returns:
            The loaded run attributes
        """
        if not self._lazy and not force:
            # Already in full mode, no need to reload
            return self._attrs

        # Load full data and mark as loaded
        result = self._load_with_fragment(RUN_FRAGMENT, RUN_FRAGMENT_NAME, force=True)
        self._full_data_loaded = True
        return result

    @property
    def config(self):
        """Get run config. Auto-loads full data if in lazy mode."""
        if self._lazy and not self._full_data_loaded and "config" not in self._attrs:
            self.load_full_data()
        return self._attrs.get("config", {})

    @property
    def summary(self):
        """Get run summary metrics. Auto-loads full data if in lazy mode."""
        if (
            self._lazy
            and not self._full_data_loaded
            and "summaryMetrics" not in self._attrs
        ):
            self.load_full_data()
        if self._summary is None:
            from wandb.old.summary import HTTPSummary

            # TODO: fix the outdir issue
            self._summary = HTTPSummary(self, self.client, summary=self.summary_metrics)
        return self._summary

    @property
    def system_metrics(self):
        """Get run system metrics. Auto-loads full data if in lazy mode."""
        if (
            self._lazy
            and not self._full_data_loaded
            and "systemMetrics" not in self._attrs
        ):
            self.load_full_data()
        return self._attrs.get("systemMetrics", {})

    @property
    def summary_metrics(self):
        """Get run summary metrics. Auto-loads full data if in lazy mode."""
        if (
            self._lazy
            and not self._full_data_loaded
            and "summaryMetrics" not in self._attrs
        ):
            self.load_full_data()
        return self._attrs.get("summaryMetrics", {})

    @property
    def rawconfig(self):
        """Get raw run config including internal keys. Auto-loads full data if in lazy mode."""
        if self._lazy and not self._full_data_loaded and "rawconfig" not in self._attrs:
            self.load_full_data()
        return self._attrs.get("rawconfig", {})

    @property
    def sweep_name(self):
        """Get sweep name. Always available since sweepName is in lightweight fragment."""
        # sweepName is included in lightweight fragment, so no need to load full data
        return self._attrs.get("sweepName")

    @property
    def path(self):
        """The path of the run. The path is a list containing the entity, project, and run_id."""
        return [
            urllib.parse.quote_plus(str(self.entity)),
            urllib.parse.quote_plus(str(self.project)),
            urllib.parse.quote_plus(str(self.id)),
        ]

    @property
    def url(self):
        """The URL of the run.

        The run URL is generated from the entity, project, and run_id. For
        SaaS users, it takes the form of `https://wandb.ai/entity/project/run_id`.
        """
        path = self.path
        path.insert(2, "runs")
        return self.client.app_url + "/".join(path)

    @property
    def metadata(self):
        """Metadata about the run from wandb-metadata.json.

        Metadata includes the run's description, tags, start time, memory
        usage and more.
        """
        if self._metadata is None:
            try:
                f = self.file("wandb-metadata.json")
                session = self.client._client.transport.session
                response = session.get(f.url, timeout=5)
                response.raise_for_status()
                contents = response.content
                self._metadata = json_util.loads(contents)
            except:  # noqa: E722
                # file doesn't exist, or can't be downloaded, or can't be parsed
                pass
        return self._metadata

    @property
    def lastHistoryStep(self):  # noqa: N802
        """Returns the last step logged in the run's history."""
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
