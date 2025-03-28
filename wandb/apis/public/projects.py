"""W&B Public API for Projects.

This module provides classes for interacting with W&B projects and their
associated data. Classes include:

Projects: A paginated collection of projects associated with an entity
- Iterate through all projects
- Access project metadata
- Query project information

Project: A single project that serves as a namespace for runs
- Access project properties
- Work with artifacts and their types
- Manage sweeps
- Generate HTML representations for Jupyter

Example:
```python
from wandb.apis.public import Api

# Initialize API
api = Api()

# Get all projects for an entity
projects_all = api.projects("entity")

# Access project data
for project in projects_all:
    print(f"Project: {project.name}")
    print(f"URL: {project.url}")

    # Get artifact types
    for artifact_type in project.artifacts_types():
        print(f"Artifact Type: {artifact_type.name}")

    # Get sweeps
    for sweep in project.sweeps():
        print(f"Sweep ID: {sweep.id}")
        print(f"State: {sweep.state}")
```

Note:
    This module is part of the W&B Public API and provides methods to access
    and manage projects. For creating new projects, use wandb.init()
    with a new project name.
"""

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


class Projects(Paginator):
    """An iterable collection of `Project` objects.

    An iterable interface to access projects created and saved by the entity.

    Example:
    ```python
    from wandb.apis.public.api import Api

    # Initialize the API client
    api = Api()

    # Find projects that belong to this entity
    projects_all = api.projects(entity="entity")

    # Iterate over files
    for project in projects_all:
        print(f"Project: {project.name}")
        print(f"- URL: {project.url}")
        print(f"- Created at: {project.created_at}")
        print(f"- Is benchmark: {project.is_benchmark}")
    ```

    """

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
    def length(self):
        """Returns the total number of projects.

        Note: This property is not available for projects.
        """
        return None

    @property
    def more(self):
        """Returns `True` if there are more projects to fetch. Returns
        `False` if there are no more projects to fetch.
        """
        if self.last_response:
            return self.last_response["models"]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        """Returns the cursor position for pagination of project results."""
        if self.last_response:
            return self.last_response["models"]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self):
        """Converts GraphQL edges to File objects."""
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
        """Returns the path of the project. The path is a list containing the
        entity and project name."""
        return [self.entity, self.name]

    @property
    def url(self):
        """Returns the URL of the project."""
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
        """Returns all artifact types associated with this project."""
        return public.ArtifactTypes(self.client, self.entity, self.name)

    @normalize_exceptions
    def sweeps(self):
        """Fetches all sweeps associated with the project."""
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
