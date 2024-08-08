"""Public API: sweeps."""

import urllib
from typing import Optional

from wandb_gql import gql

import wandb
from wandb import util
from wandb.apis import public
from wandb.apis.attrs import Attrs
from wandb.sdk.lib import ipython

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
                raise ValueError("Could not find sweep {}".format(self))
            self._attrs = sweep._attrs
            self.runs = sweep.runs

        return self._attrs

    @property
    def order(self):
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
        sweep.runs = public.Runs(
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
