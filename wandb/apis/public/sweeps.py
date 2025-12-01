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

import urllib

from wandb_gql import gql

import wandb
from wandb import util
from wandb.apis import public
from wandb.apis.attrs import Attrs
from wandb.apis.paginator import SizedPaginator
from wandb.apis.public.api import RetryingClient
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

    QUERY = gql(
        f"""#graphql
        query GetSweeps($project: String!, $entity: String!, $cursor: String, $perPage: Int = 50) {{
            project(name: $project, entityName: $entity) {{
                totalSweeps
                sweeps(after: $cursor, first: $perPage) {{
                    edges {{
                        node {{
                            ...SweepFragment
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
        {SWEEP_FRAGMENT}
        """
    )

    def __init__(
        self,
        client: RetryingClient,
        entity: str,
        project: str,
        per_page: int = 50,
    ) -> Sweeps:
        """An iterable collection of `Sweep` objects.

        Args:
            client: The API client used to query W&B.
            entity: The entity which owns the sweeps.
            project: The project which contains the sweeps.
            per_page: The number of sweeps to fetch per request to the API.
        """
        self.client = client
        self.entity = entity
        self.project = project
        variables = {
            "project": self.project,
            "entity": self.entity,
        }
        super().__init__(client, variables, per_page)

    @property
    def _length(self):
        """The total number of sweeps in the project.

        <!-- lazydoc-ignore: internal -->
        """
        if not self.last_response:
            self._load_page()

        return (
            self.last_response["project"]["totalSweeps"]
            if self.last_response["project"]["totalSweeps"] is not None
            else 0
        )

    @property
    def more(self):
        """Returns whether there are more sweeps to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return bool(
                self.last_response["project"]["sweeps"]["pageInfo"]["hasNextPage"]
            )
        else:
            return True

    @property
    def cursor(self):
        """Returns the cursor for the next page of sweeps.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return self.last_response["project"]["sweeps"]["pageInfo"]["endCursor"]
        else:
            return None

    def update_variables(self):
        """Updates the variables for the next page of sweeps.

        <!-- lazydoc-ignore: internal -->
        """
        self.variables.update({"perPage": self.per_page, "cursor": self.cursor})

    def convert_objects(self):
        """Converts the last GraphQL response into a list of `Sweep` objects.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response is None or self.last_response.get("project") is None:
            raise ValueError("Could not find project {}".format(self.project))

        if self.last_response["project"]["totalSweeps"] < 1:
            return []

        return [
            # match format of existing public sweep apis
            public.Sweep(
                self.client,
                self.entity,
                self.project,
                e["node"]["name"],
            )
            for e in self.last_response["project"]["sweeps"]["edges"]
        ]

    def __repr__(self):
        return f"<Sweeps {self.entity}/{self.project}>"


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

    QUERY = gql(
        """
    query Sweep($project: String, $entity: String, $name: String!) {
        project(name: $project, entityName: $entity) {
            sweep(sweepName: $name) {
                id
                name
                displayName
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
        """The entity associated with the sweep."""
        return self._entity

    @property
    def username(self):
        """Deprecated. Use `Sweep.entity` instead."""
        wandb.termwarn("Sweep.username is deprecated. please use Sweep.entity instead.")
        return self._entity

    @property
    def config(self):
        """The sweep configuration used for the sweep."""
        return util.load_yaml(self._attrs["config"])

    def load(self, force: bool = False):
        """Fetch and update sweep data logged to the run from GraphQL database.

        <!-- lazydoc-ignore: internal -->
        """
        if force or not self._attrs:
            sweep = self.get(self.client, self.entity, self.project, self.id)
            if sweep is None:
                raise ValueError("Could not find sweep {}".format(self))
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
    def expected_run_count(self) -> int | None:
        """Return the number of expected runs in the sweep or None for infinite runs."""
        return self._attrs.get("runCountExpected")

    @property
    def path(self):
        """Returns the path of the project.

        The path is a list containing the entity, project name, and sweep ID."""
        return [
            urllib.parse.quote_plus(str(self.entity)),
            urllib.parse.quote_plus(str(self.project)),
            urllib.parse.quote_plus(str(self.id)),
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
        return self.client.app_url + "/".join(path)

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
        client: RetryingClient,
        entity: str | None = None,
        project: str | None = None,
        sid: str | None = None,
        order: str | None = None,
        query: str | None = None,
        **kwargs,
    ):
        """Execute a query against the cloud backend.

        Args:
            client: The client to use to execute the query.
            entity: The entity (username or team) that owns the project.
            project: The name of the project to fetch sweep from.
            sid: The sweep ID to query.
            order: The order in which the sweep's runs are returned.
            query: The query to use to execute the query.
            **kwargs: Additional keyword arguments to pass to the query.
        """
        if not order:
            order = "+created_at"

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
