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

from typing import Any

from typing_extensions import override
from wandb_gql import gql

from wandb._pydantic import Connection
from wandb._strutils import nameof
from wandb.apis import public
from wandb.apis.attrs import Attrs
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import Paginator
from wandb.apis.public.api import RetryingClient
from wandb.apis.public.sweeps import Sweeps
from wandb.sdk.lib import ipython
from wandb.sdk.projects._generated import (
    FETCH_PROJECT_GQL,
    FETCH_PROJECTS_GQL,
    FetchProject,
    FetchProjects,
    ProjectFragment,
)

_ProjectConnection = Connection[ProjectFragment]


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

    last_response: _ProjectConnection | None

    QUERY = gql(FETCH_PROJECTS_GQL)

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

    @override
    def _update_response(self) -> None:
        """Fetch and validate the response data for the current page."""
        data = self.client.execute(self.QUERY, variable_values=self.variables)
        result = FetchProjects.model_validate(data)

        # Extract the inner `*Connection` result for faster/easier access.
        if not (conn := result.models):
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")

        self.last_response = _ProjectConnection.model_validate(conn)

    @property
    def length(self) -> None:
        """Returns the total number of projects.

        Note: This property is not available for projects.

        <!-- lazydoc-ignore: internal -->
        """
        # For backwards compatibility, even though this isn't a SizedPaginator
        return None

    @property
    def more(self) -> bool:
        """Returns `True` if there are more projects to fetch. Returns
        `False` if there are no more projects to fetch.

        <!-- lazydoc-ignore: internal -->
        """
        return (conn := self.last_response) is None or conn.has_next

    @property
    def cursor(self) -> str | None:
        """Returns the cursor position for pagination of project results.

        <!-- lazydoc-ignore: internal -->
        """
        return conn.next_cursor if (conn := self.last_response) else None

    def convert_objects(self) -> list[Project]:
        """Converts GraphQL edges to File objects.

        <!-- lazydoc-ignore: internal -->
        """
        return [
            Project(self.client, self.entity, node.name, node.model_dump())
            for node in self.last_response.nodes()
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

    QUERY = gql(FETCH_PROJECT_GQL)

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

    def _load(self) -> None:
        from requests import HTTPError

        variable_values = {"project": self.name, "entity": self.entity}
        try:
            data = self.client.execute(self.QUERY, variable_values)
        except HTTPError as e:
            raise ValueError(f"Unable to fetch project ID: {variable_values!r}") from e

        project = FetchProject.model_validate(data).project
        self._attrs = project.model_dump() if project else {}
        self._is_loaded = True

    @property
    def path(self) -> list[str]:
        """Returns the path of the project. The path is a list containing the
        entity and project name."""
        return [self.entity, self.name]

    @property
    def url(self) -> str:
        """Returns the URL of the project."""
        return self.client.app_url + "/".join(self.path + ["workspace"])

    def to_html(self, height: int = 420, hidden: bool = False) -> str:
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
    def artifacts_types(self, per_page: int = 50) -> public.ArtifactTypes:
        """Returns all artifact types associated with this project."""
        return public.ArtifactTypes(self.client, self.entity, self.name)

    @normalize_exceptions
    def sweeps(self, per_page: int = 50) -> Sweeps:
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

    def __getattr__(self, name: str) -> Any:
        if not self._is_loaded:
            self._load()

        return super().__getattr__(name)
