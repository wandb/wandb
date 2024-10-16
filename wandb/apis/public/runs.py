"""Public API: runs."""

import json
import os
import sys
import tempfile
import time
import urllib
from typing import TYPE_CHECKING, Any, Collection, Dict, List, Mapping, Optional

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

from wandb_gql import gql

import wandb
from wandb import env, util
from wandb.apis import public
from wandb.apis.attrs import Attrs
from wandb.apis.internal import Api as InternalApi
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import Paginator
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


class Runs(Paginator):
    """An iterable collection of runs associated with a project and optional filter.

    This is generally used indirectly via the `Api`.runs method.
    """

    QUERY = gql(
        """
        query Runs($project: String!, $entity: String!, $cursor: String, $perPage: Int = 50, $order: String, $filters: JSONString) {{
            project(name: $project, entityName: $entity) {{
                runCount(filters: $filters)
                readOnly
                runs(filters: $filters, after: $cursor, first: $perPage, order: $order) {{
                    edges {{
                        node {{
                            ...RunFragment
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
        {}
        """.format(RUN_FRAGMENT)
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
            raise ValueError("Could not find project {}".format(self.project))
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
        keys: Optional[List[str]] = None,
        x_axis: str = "_step",
        format: Literal["default", "pandas", "polars"] = "default",
        stream: Literal["default", "system"] = "default",
    ):
        """Return sampled history metrics for all runs that fit the filters conditions.

        Arguments:
            samples : (int, optional) The number of samples to return per run
            keys : (list[str], optional) Only return metrics for specific keys
            x_axis : (str, optional) Use this metric as the xAxis defaults to _step
            format : (Literal, optional) Format to return data in, options are "default", "pandas", "polars"
            stream : (Literal, optional) "default" for metrics, "system" for machine metrics
        Returns:
            pandas.DataFrame: If format="pandas", returns a `pandas.DataFrame` of history metrics.
            polars.DataFrame: If format="polars", returns a `polars.DataFrame` of history metrics.
            list of dicts: If format="default", returns a list of dicts containing history metrics with a run_id key.
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
            combined_df.sort_values("run_id", inplace=True)
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
            combined_df = pl.concat(histories, how="align")
            # sort columns for consistency
            combined_df = combined_df.select(sorted(combined_df.columns)).sort("run_id")

            return combined_df

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
        query Run($project: String!, $entity: String!, $name: String!) {{
            project(name: $project, entityName: $entity) {{
                run(name: $name) {{
                    ...RunFragment
                }}
            }}
        }}
        {}
        """.format(RUN_FRAGMENT)
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

        try:
            self._attrs["summaryMetrics"] = (
                json.loads(self._attrs["summaryMetrics"])
                if self._attrs.get("summaryMetrics")
                else {}
            )
        except json.decoder.JSONDecodeError:
            # ignore invalid utf-8 or control characters
            self._attrs["summaryMetrics"] = json.loads(
                self._attrs["summaryMetrics"],
                strict=False,
            )
        self._attrs["systemMetrics"] = (
            json.loads(self._attrs["systemMetrics"])
            if self._attrs.get("systemMetrics")
            else {}
        )
        if self._attrs.get("user"):
            self.user = public.User(self.client, self._attrs["user"])
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
        mutation UpsertBucket($id: String!, $description: String, $display_name: String, $notes: String, $tags: [String!], $config: JSONString!, $groupName: String) {{
            upsertBucket(input: {{id: $id, description: $description, displayName: $display_name, notes: $notes, tags: $tags, config: $config, groupName: $groupName}}) {{
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
    def files(self, names=None, per_page=50):
        """Return a file path for each file named.

        Arguments:
            names (list): names of the requested files, if empty returns all files
            per_page (int): number of results per page.

        Returns:
            A `Files` object, which is an iterator over `File` objects.
        """
        return public.Files(self.client, self, names or [], per_page)

    @normalize_exceptions
    def file(self, name):
        """Return the path of a file with a given name in the artifact.

        Arguments:
            name (str): name of requested file.

        Returns:
            A `File` matching the name argument.
        """
        return public.Files(self.client, self, [name])[0]

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
        return public.Files(self.client, self, [name])[0]

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
            pd = util.get_module("pandas")
            if pd:
                lines = pd.DataFrame.from_records(lines)
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
            page_size (int, optional): size of pages to fetch from the api.
            min_step (int, optional): the minimum number of pages to scan at a time.
            max_step (int, optional): the maximum number of pages to scan at a time.

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
    def logged_artifacts(self, per_page=100):
        return public.RunArtifacts(self.client, self, mode="logged", per_page=per_page)

    @normalize_exceptions
    def used_artifacts(self, per_page=100):
        return public.RunArtifacts(self.client, self, mode="used", per_page=per_page)

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
                "Manually create one with `wandb artifact put`"
            )
        else:
            raise ValueError("You must pass a wandb.Api().artifact() to use_artifact")

    @normalize_exceptions
    def log_artifact(
        self,
        artifact: "wandb.Artifact",
        aliases: Optional[Collection[str]] = None,
        tags: Optional[Collection[str]] = None,
    ):
        """Declare an artifact as output of a run.

        Arguments:
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
            raise ValueError("You must pass a wandb.Api().artifact() to use_artifact")
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
                contents = util.download_file_into_memory(f.url, wandb.Api().api_key)
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
