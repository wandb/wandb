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

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from typing_extensions import override

from wandb._strutils import nameof
from wandb.apis import public
from wandb.apis.attrs import Attrs
from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import RelayPaginator
from wandb.apis.public.service_api import ServiceApi
from wandb.apis.public.sweeps import Sweeps
from wandb.sdk.lib import ipython
from wandb.sdk.lib.service.service_connection import WandbApiFailedError

if TYPE_CHECKING:
    from wandb._pydantic import Connection
    from wandb.apis._generated import ProjectFragment


class Projects(RelayPaginator["ProjectFragment", "Project"]):
    """An lazy iterator of `Project` objects.

    An iterable interface to access projects created and saved by the entity.

    Args:
        service_api: Interface to the wandb-core service that performs
            W&B API calls for this collection.
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

    QUERY: ClassVar[str | None] = None
    last_response: Connection[ProjectFragment] | None

    def __init__(
        self,
        service_api: ServiceApi,
        entity: str,
        per_page: int = 50,
    ) -> None:
        """An iterable collection of `Project` objects.

        Args:
            service_api: The service API used to query W&B.
            entity: The entity which owns the projects.
            per_page: The number of projects to fetch per request to the API.
        """
        if self.QUERY is None:
            from wandb.apis._generated import GET_PROJECTS_GQL

            type(self).QUERY = GET_PROJECTS_GQL

        self.entity = entity
        self._service_api = service_api
        super().__init__(service_api, variables={"entity": entity}, per_page=per_page)

    @override
    def _update_response(self) -> None:
        """Fetch and validate the response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.apis._generated import GetProjects, ProjectFragment

        result = self._execute_query(parse=GetProjects.model_validate_json)
        if not (conn := result.models):
            raise ValueError(f"Unable to parse {nameof(type(self))!r} response data")
        self.last_response = Connection[ProjectFragment].model_validate(conn)

    @property
    def length(self) -> None:
        """Returns the total number of projects.

        Note: This property is not available for projects.

        <!-- lazydoc-ignore: internal -->
        """
        # For backwards compatibility, even though this isn't a SizedPaginator
        return None

    def _convert(self, node: ProjectFragment) -> Project:
        return Project(
            self._service_api,
            self.entity,
            node.name,
            node.model_dump(),
        )

    def __repr__(self):
        return f"<Projects {self.entity}>"


class Project(Attrs):
    """A project is a namespace for runs.

    Args:
        service_api: Interface to the wandb-core service that performs
            W&B API calls for this project.
        name (str): The name of the project.
        entity (str): The entity name that owns the project.
    """

    def __init__(
        self,
        service_api: ServiceApi,
        entity: str,
        project: str,
        attrs: Mapping[str, Any],
    ) -> None:
        """A single project associated with an entity.

        Args:
            service_api: The service API used to query W&B.
            entity: The entity which owns the project.
            project: The name of the project to query.
            attrs: The attributes of the project.
        """
        super().__init__(attrs)
        self._is_loaded = bool(attrs)
        self._service_api = service_api
        self.name = project
        self.entity = entity

    def _load(self) -> None:
        from wandb.apis._generated import GET_PROJECT_GQL, GetProject

        gql_vars = {"name": self.name, "entity": self.entity}
        try:
            data = self._service_api.execute_graphql(
                GET_PROJECT_GQL,
                variables=gql_vars,
                parse=GetProject.model_validate_json,
            )
        except WandbApiFailedError as e:
            raise ValueError(f"Unable to fetch project ID: {gql_vars!r}") from e

        project = data.project
        self._attrs = project.model_dump() if project else {}
        self._is_loaded = True

    @property
    def owner(self) -> public.User:
        """Returns the project owner as a User object.

        Raises:
            ValueError: when no user information is found for the project.
        """
        if not self._is_loaded:
            self._load()
        if "user" not in self._attrs:
            raise ValueError(f"No user found for project {self.name}")
        return public.User(self._service_api, self._attrs["user"])

    @property
    def path(self) -> list[str]:
        """Returns the path of the project. The path is a list containing the
        entity and project name."""
        return [self.entity, self.name]

    @property
    def url(self) -> str:
        """Returns the URL of the project."""
        return self._service_api.app_url + "/".join(self.path + ["workspace"])

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
        return public.ArtifactTypes(self._service_api, self.entity, self.name)

    @normalize_exceptions
    def collections(
        self,
        filters: Mapping[str, Any] | None = None,
        order: str | None = None,
        per_page: int = 50,
    ) -> public.ProjectArtifactCollections:
        """Returns all artifact collections associated with this project.

        Args:
            filters: Optional mapping of filters to apply to the query.
            order: Optional string to specify the order of the results.
                If you prepend order with a + order is ascending (default).
                If you prepend order with a - order is descending.
            per_page: The number of artifact collections to fetch per page.
                Default is 50.
        """
        return public.ProjectArtifactCollections(
            self._service_api,
            self.entity,
            self.name,
            filters=filters,
            order=order,
            per_page=per_page,
        )

    @normalize_exceptions
    def sweeps(
        self,
        per_page: int = 50,
        filters: dict[str, Any] | None = None,
        order: str | None = None,
    ) -> Sweeps:
        """Return a paginated collection of sweeps in this project.

        Args:
            per_page: The number of sweeps to fetch per request to the API.
            filters: (dict) queries for specific sweeps using the runs filters,
                See wandb/apis/public/api.py:runs for more details.

        Returns:
            A `Sweeps` object, which is an iterable collection of `Sweep` objects.
        """
        return Sweeps(
            self._service_api,
            self.entity,
            self.name,
            per_page=per_page,
            filters=filters,
        )

    @property
    def id(self) -> str:
        if not self._is_loaded:
            self._load()

        if "id" not in self._attrs:
            raise ValueError(f"Project {self.name} not found")

        return self._attrs["id"]

    @override
    def __getattr__(self, name: str) -> Any:
        if not self._is_loaded:
            self._load()
        return super().__getattr__(name)
