"""W&B Public API for Project objects.

This module provides classes for interacting with W&B projects and their
associated data.

Example:
```python
from wandb.apis.public import Api

# Get all projects for an entity
projects = Api().projects("entity")

# Access project data
for project in projects:
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

from __future__ import annotations

from requests import HTTPError
from wandb_gql import gql

from wandb.apis import public
from wandb.apis.attrs import Attrs
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import Paginator
from wandb.apis.public.api import RetryingClient
from wandb.apis.public.sweeps import Sweeps
from wandb.sdk.lib import ipython

PROJECT_FRAGMENT = """fragment ProjectFragment on Project {
    id
    name
    entityName
    createdAt
    isBenchmark
}"""


class Projects(Paginator["Project"]):
    """An lazy iterator of `Project` objects.

    An iterable interface to access projects created and saved by the entity.

    Args:
        client (`wandb.apis.internal.Api`): The API client instance to use.
        entity (str): The entity name (username or team) to fetch projects for.
        per_page (int): Number of projects to fetch per request (default is 50).

    Example:
    ```python
    from wandb.apis.public.api import Api

    # Find projects that belong to this entity
    projects = Api().projects(entity="entity")

    # Iterate over files
    for project in projects:
        print(f"Project: {project.name}")
        print(f"- URL: {project.url}")
        print(f"- Created at: {project.created_at}")
        print(f"- Is benchmark: {project.is_benchmark}")
    ```
    """

    QUERY = gql(f"""#graphql
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
        {PROJECT_FRAGMENT}
    """)

    def __init__(
        self,
        client: RetryingClient,
        entity: str,
        per_page: int = 50,
    ) -> Projects:
        """An iterable collection of `Project` objects.

        Args:
            client: The API client used to query W&B.
            entity: The entity which owns the projects.
            per_page: The number of projects to fetch per request to the API.
        """
        self.client = client
        self.entity = entity
        variables = {
            "entity": self.entity,
        }
        super().__init__(client, variables, per_page)

    @property
    def length(self) -> None:
        """Returns the total number of projects.

        Note: This property is not available for projects.

        <!-- lazydoc-ignore: internal -->
        """
        # For backwards compatibility, even though this isn't a SizedPaginator
        return None

    @property
    def more(self):
        """Returns `True` if there are more projects to fetch. Returns
        `False` if there are no more projects to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return self.last_response["models"]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self):
        """Returns the cursor position for pagination of project results.

        <!-- lazydoc-ignore: internal -->
        """
        if self.last_response:
            return self.last_response["models"]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self):
        """Converts GraphQL edges to File objects.

        <!-- lazydoc-ignore: internal -->
        """
        return [
            Project(self.client, self.entity, p["node"]["name"], p["node"])
            for p in self.last_response["models"]["edges"]
        ]

    def __repr__(self):
        return f"<Projects {self.entity}>"


class Project(Attrs):
    """A project is a namespace for runs.

    Args:
        client: W&B API client instance.
        name (str): The name of the project.
        entity (str): The entity name that owns the project.
    """

    QUERY = gql(f"""#graphql
        query Project($project: String!, $entity: String!) {{
            project(name: $project, entityName: $entity) {{
                ...ProjectFragment
            }}
        }}
        {PROJECT_FRAGMENT}
    """)

    def __init__(
        self,
        client: RetryingClient,
        entity: str,
        project: str,
        attrs: dict,
    ) -> Project:
        """A single project associated with an entity.

        Args:
            client: The API client used to query W&B.
            entity: The entity which owns the project.
            project: The name of the project to query.
            attrs: The attributes of the project.
        """
        super().__init__(dict(attrs))
        self._is_loaded = bool(attrs)
        self.client = client
        self.name = project
        self.entity = entity

    def _load(self):
        variable_values = {"project": self.name, "entity": self.entity}
        try:
            response = self.client.execute(self.QUERY, variable_values)
        except HTTPError as e:
            raise ValueError(f"Unable to fetch project ID: {variable_values!r}") from e

        self._attrs = response["project"]
        self._is_loaded = True

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
        """Generate HTML containing an iframe displaying this project.

        <!-- lazydoc-ignore: internal -->
        """
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
    def sweeps(self, per_page=50):
        """Return a paginated collection of sweeps in this project.

        Args:
            per_page: The number of sweeps to fetch per request to the API.

        Returns:
            A `Sweeps` object, which is an iterable collection of `Sweep` objects.
        """
        return Sweeps(self.client, self.entity, self.name, per_page=per_page)

    @property
    def id(self) -> str:
        if not self._is_loaded:
            self._load()

        if "id" not in self._attrs:
            raise ValueError(f"Project {self.name} not found")

        return self._attrs["id"]

    def __getattr__(self, name: str):
        if not self._is_loaded:
            self._load()

        return super().__getattr__(name)
