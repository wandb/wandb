"""Public API: projects."""

from wandb_gql import gql

from wandb.apis import public
from wandb.apis.attrs import Attrs
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import Paginator
from wandb.sdk.lib import ipython

PROJECT_FRAGMENT = """fragment ProjectFragment on Project {
    id
    name
    entityName
    createdAt
    isBenchmark
}"""


class Projects(Paginator["Project"]):
    """An iterable collection of `Project` objects."""

    QUERY = gql(
        """
        query Projects($entity: String, $cursor: String, $perPage: Int = 50) {{
            models(entityName: $entity, after: $cursor, first: $perPage) {{
                edges {{
                    node {{
                        ...ProjectFragment
                    }}
                    cursor
                }}
                pageInfo {{
                    endCursor
                    hasNextPage
                }}
            }}
        }}
        {}
        """.format(PROJECT_FRAGMENT)
    )

    def __init__(self, client, entity, per_page=50):
        self.client = client
        self.entity = entity
        variables = {
            "entity": self.entity,
        }
        super().__init__(client, variables, per_page)

    @property
    def length(self) -> None:
        # For backwards compatibility, even though this isn't a SizedPaginator
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
        return public.ArtifactTypes(self.client, self.entity, self.name)

    @normalize_exceptions
    def sweeps(self):
        query = gql(
            """
            query GetSweeps($project: String!, $entity: String!) {{
                project(name: $project, entityName: $entity) {{
                    totalSweeps
                    sweeps {{
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
            {}
            """.format(public.SWEEP_FRAGMENT)
        )
        variable_values = {"project": self.name, "entity": self.entity}
        ret = self.client.execute(query, variable_values)
        if ret["project"]["totalSweeps"] < 1:
            return []

        return [
            # match format of existing public sweep apis
            public.Sweep(
                self.client,
                self.entity,
                self.name,
                e["node"]["name"],
            )
            for e in ret["project"]["sweeps"]["edges"]
        ]
