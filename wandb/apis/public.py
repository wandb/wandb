import ast
import datetime
from functools import partial
import json
import logging
import os
import platform
import re
import shutil
import sys
import tempfile

from dateutil.relativedelta import relativedelta
from graphql.language.ast import Document
from gql import Client, gql
from gql.client import RetryError
from gql.transport.requests import ExecutionResult, RequestsHTTPTransport
import requests
import six
from six.moves import urllib
import wandb
from wandb import __version__, env, util
from wandb.apis.internal import Api as InternalApi
from wandb.apis.normalize import normalize_exceptions
from wandb.data_types import WBValue
from wandb.errors.term import termlog
from wandb.old.summary import HTTPSummary
import yaml

PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.lib import retry
    from wandb.sdk.interface import artifacts
else:
    from wandb.sdk_py27.lib import retry
    from wandb.sdk_py27.interface import artifacts


if wandb.TYPE_CHECKING:  # type: ignore
    from typing import (
        Optional,
        Union,
        List,
        Sequence,
        Dict,
        Any,
        IO,
        Tuple,
    )  # noqa: F401


# Only retry requests for 20 seconds in the public api
RETRY_TIMEDELTA = datetime.timedelta(seconds=20)
WANDB_INTERNAL_KEYS = {"_wandb", "wandb_version"}
PROJECT_FRAGMENT = """fragment ProjectFragment on Project {
    id
    name
    entityName
    createdAt
    isBenchmark
}"""

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
FILE_FRAGMENT = """fragment RunFilesFragment on Run {
    files(names: $fileNames, after: $fileCursor, first: $fileLimit) {
        edges {
            node {
                id
                name
                url(upload: $upload)
                directUrl
                sizeBytes
                mimetype
                updatedAt
                md5
            }
            cursor
        }
        pageInfo {
            endCursor
            hasNextPage
        }
    }
}"""

ARTIFACTS_TYPES_FRAGMENT = """
fragment ArtifactTypesFragment on ArtifactTypeConnection {
    edges {
         node {
             id
             name
             description
             createdAt
         }
         cursor
    }
    pageInfo {
        endCursor
        hasNextPage
    }
}
"""

ARTIFACT_FRAGMENT = """
fragment ArtifactFragment on Artifact {
    id
    digest
    description
    state
    size
    createdAt
    updatedAt
    labels
    metadata
    versionIndex
    aliases {
        artifactCollectionName
        alias
    }
    artifactSequence {
        id
        name
    }
    artifactType {
        id
        name
    }
    commitHash
}
"""

# TODO, factor out common file fragment
ARTIFACT_FILES_FRAGMENT = """fragment ArtifactFilesFragment on Artifact {
    files(names: $fileNames, after: $fileCursor, first: $fileLimit) {
        edges {
            node {
                id
                name: displayName
                url
                sizeBytes
                mimetype
                updatedAt
                digest
                md5
            }
            cursor
        }
        pageInfo {
            endCursor
            hasNextPage
        }
    }
}"""


logger = logging.getLogger(__name__)


class _Old_Api(object):  # For backward compatibility
    def artifact(self, name: str, type: Optional[str] = None) -> "Artifact":
        path = name.split("/")
        path.insert(-1, "artifacts")
        return self.get("/".join(path))

    def artifact_type(
        self, type_name: str, project: Optional[str] = None
    ) -> "ArtifactType":
        project = project or self.settings["project"]
        entity = self.settings["entity"] or self.default_entity
        path = project.split("/")
        if len(path) > 1:
            assert len(path) == 2
            entity, project = path
        project = Entity(client=self._client, name=entity).project(name=project)
        return ArtifactType(client=self._client, project=project, type_name=type_name)

    def artifact_versions(
        self, type_name: str, name: str, per_page: int = 50
    ) -> "ArtifactVersions":
        project = project or self.settings["project"]
        entity = self.settings["entity"] or self.default_entity
        path = name.split("/")
        collection_name = path.pop()
        if path:
            project = path.pop()
        if path:
            entity = path.pop()
        project = Entity(self._client, name=entity).project(name=project)
        artifact_type = ArtifactType(
            client=self.client, project=project, type_name=type_name
        )
        return artifact_type.collection(collection_name).versions(per_page=per_page)

    def artifact_types(self, project: str = None) -> "ProjectArtifactTypes":
        project = project or self.settings["project"]
        entity = self.settings["entity"] or self.default_entity
        path = project.split("/")
        if len(path) > 1:
            assert len(path) == 2
            entity, project = path
        project = Entity(client=self._client, name=entity).project(name=project)
        return ProjectArtifactTypes(client=self._client, project=project)

    def runs(
        self,
        path: str = "",
        filters: Optional[Dict] = None,
        order: str = "-created_at",
        per_page: int = 50,
    ) -> "Runs":
        return self.get(path, filter=filters, order=order, per_page=per_page)

    def run(self, path: str) -> "Run":
        return self.get(path)

    def create_run(
        self, run_id: str, entity: Optional[str] = None, project: Optional[str] = None
    ) -> "Run":
        entity = entity or self.settings.get("entity", self.default_entity)
        project = project or self.settings["project"]
        return (
            Entity(client=self._client, name=entity)
            .project(name=project)
            .create_run(run_id=run_id)
        )

    def projects(self, entity: Optional[str] = None, per_page: int = 200) -> "Projects":
        entity = entity or self.settings.get("entity", self.default_entity)
        return Enity(client=self._client, name=entity).projects(per_page=per_page)

    def reports(
        self,
        path: str = "",
        name: Optional[Union[List[str], str]] = None,
        per_page: int = 50,
    ) -> "Reports":
        if path[-1] == "/":
            path += "reports"
        else:
            path += "/reports"
        return self.get(path, names=name, per_page=per_page)

    def sweep(self, path: str = "") -> "Sweep":
        path = path.split("/")
        path.insert(-1, "sweeps")
        path = "/".join(path)
        return self.get(path)

    def sync_tensorboard(
        self,
        root_dir: str,
        run_id: Optional[str] = None,
        project: Optional[str] = None,
        entity: Optional[str] = None,
    ) -> "Run":
        project = project or self.settings["project"]
        entity = entity or self.settings.get("entity", self.default_entity)
        return (
            Entity(self._client, name=entity)
            .project(name=project)
            .sync_tensorboard(root_dir=root_dir, run_id=run_id)
        )


class Api(_Old_Api):
    _HTTP_TIMEOUT = env.get_http_timeout(9)
    VIEWER_QUERY = gql(
        """
    query Viewer{
        viewer {
            id
            flags
            entity
            teams {
                edges {
                    node {
                        name
                    }
                }
            }
        }
    }
    """
    )

    def __init__(self, overrides: Optional[Dict] = None) -> None:
        self.settings = InternalApi().settings()
        if self.api_key is None:
            wandb.login()
        overrides = overrides or {}
        self.settings.update(overrides)
        if "username" in overrides and "entity" not in overrides:
            wandb.termwarn(
                'Passing "username" to Api is deprecated. please use "entity" instead.'
            )
            self.settings["entity"] = overrides["username"]
        self._base_client = Client(
            transport=RequestsHTTPTransport(
                headers={"User-Agent": self.user_agent, "Use-Admin-Privileges": "true"},
                use_json=True,
                # this timeout won't apply when the DNS lookup fails. in that case, it will be 60s
                # https://bugs.python.org/issue22889
                timeout=self._HTTP_TIMEOUT,
                auth=("api", self.api_key),
                url="%s/graphql" % self.settings["base_url"],
            )
        )
        self._client = RetryingClient(self._base_client)
        self._default_entity = None

    @property
    def default_entity(self) -> str:
        if self._default_entity is None:
            res = self._client.execute(self.VIEWER_QUERY)
            self._default_entity = (res.get("viewer") or {}).get("entity")
        return self._default_entity

    @property
    def api_key(self) -> str:
        key = os.environ.get("WANDB_API_KEY")
        if key:
            return key
        auth = requests.utils.get_netrc_auth(self.settings["base_url"])
        if auth:
            return auth[-1]

    @property
    def user_agent(self) -> str:
        return "W&B Public Client %s" % __version__

    def get(
        self, path, **kwargs
    ) -> Union[
        "Entity", "Project", "Run", "Runs", "Sweep", "Sweeps", "Report", "Reports"
    ]:
        """Parses paths in the following formats:

        url: entity/project/runs/run_id
        path: entity/project/run_id
        docker: entity/project:run_id

        entity is optional and will fallback to the current logged in user.
        """
        project = self.settings["project"]
        entity = self.settings["entity"] or self.default_entity

        if path:
            parts = [p for p in path.split("/") if p]
            if not parts:
                raise ValueError("Empty path!")
            last = parts.pop()
            if last == "runs":
                path_type = "runs"
            elif last == "sweeps":
                path_type = "sweeps"
            elif last == "reports":
                path_type = "reports"
            elif parts[-1] == "sweeps":
                path_type = "sweep"
                sweep_id = last
                parts.pop()
            elif parts[-1] == "reports":
                path_type = "report"
                report_name = last
                parts.pop()
            elif parts[-1] == "artifacts":
                path_type = "artifact"
                artifact_name = last
                parts.pop()
            else:
                if ":" in last:
                    s = last.split(":", 1)
                    last = s[-1]
                    parts.append(s[0])
                path_type = "run"
                run_id = last
                if parts[-1] == "runs":
                    parts.pop()
            if parts:
                project = parts.pop()
            if parts:
                entity = parts.pop()
            if path_type == "run":
                return (
                    Entity(client=self._client, name=entity)
                    .project(name=project)
                    .run(run_id=run_id)
                )
            elif path_type == "runs":
                return (
                    Entity(client=self._client, name=entity)
                    .project(name=project)
                    .runs(
                        filter=kwargs.get("filters", kwargs.get("filter", {})),
                        order=kwargs.get("order"),
                        per_page=kwargs.get("per_page", 50),
                    )
                )
            elif path_type == "sweep":
                return (
                    Entity(client=self._client, name=entity)
                    .project(name=project)
                    .sweep(sweep_id=sweep_id)
                )
            elif path_type == "sweeps":
                return (
                    Entity(client=self._client, name=entity)
                    .project(name=project)
                    .sweeps()
                )
            elif path_type == "reports":
                return (
                    Entity(client=self._client, name=entity)
                    .project(name=project)
                    .reports(
                        names=kwargs.get("names", []),
                        per_page=kwargs.get("per_page", 50),
                    )
                )
            elif path_type == "report":
                return (
                    Entity(client=self._client, name=entity)
                    .project(name=project)
                    .report(name=report_name)
                )
            elif path_type == "artifact":
                return (
                    Entity(client=self._client, name=entity)
                    .project(name=project)
                    .artifact(name=artifact_name)
                )
        else:
            project = kwargs.get("project", project)
            entity = kwargs.get("entity", entity)
            if "run" in kwargs or "run_id" in kwargs:
                run_id = kwargs.get("run", kwargs["run_id"])
                return (
                    Entity(client=self._client, name=entity)
                    .project(name=project)
                    .run(run_id=run_id)
                )
            elif "sweep" in kwargs or "sweep_id" in kwargs:
                sweep_id = kwargs.get("sweep", kwargs.get("sweep_id"))
                return (
                    Entity(client=self._client, name=entity)
                    .project(name=project)
                    .sweep(sweep_id=sweep_id)
                )
            elif "project" in kwargs:
                return Entity(client=self._client, name=entity).project(name=project)
            elif "entity" in kwargs:
                return Entity(client=self._client, name=entity)
            elif "report" in kwargs:
                return (
                    Entity(client=self._client, name=entity)
                    .project(name=project)
                    .report(name=kwargs["report"])
                )
            else:
                # .get() returns default entity?
                return Entity(client=self._client, name=entity)


class RetryingClient(object):
    def __init__(self, client: Client) -> None:
        self._client = client

    @property
    def app_url(self) -> str:
        return util.app_url(self._client.transport.url).replace("/graphql", "/")

    @retry.retriable(
        retry_timedelta=RETRY_TIMEDELTA,
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException),
    )
    def execute(self, *args, **kwargs) -> ExecutionResult:
        return self._client.execute(*args, **kwargs)


class Entity(object):
    def __init__(self, client: RetryingClient, name: str) -> None:
        self.client = client
        self.name = name

    def projects(self, per_page: int = 200) -> "Projects":
        return Projects(client=self.client, entity=self, per_page=per_page)

    def project(self, name: str) -> "Project":
        return Project(client=self.client, entity=self, name=name)

    def __repr__(self) -> str:
        return self.name


class Attrs(object):
    def __init__(self, attrs: Optional[Dict]) -> None:
        attrs = attrs or {}
        self._attrs = attrs

    def _snake_to_camel(self, string: str) -> str:
        camel = "".join([i.title() for i in string.split("_")])
        return camel[0].lower() + camel[1:]

    def __getattr__(self, name: str) -> str:
        key = self._snake_to_camel(name)
        if key == "user":
            raise AttributeError()
        if key in self._attrs.keys():
            return self._attrs[key]
        elif name in self._attrs.keys():
            return self._attrs[name]
        else:
            raise AttributeError(
                "'{}' object has no attribute '{}'".format(repr(self), name)
            )


class Paginator(object):
    QUERY = None

    def __init__(
        self, client: RetryingClient, variables: Dict, per_page: Optional[int] = None
    ):
        self.client = client
        self.variables = variables
        # We don't allow unbounded paging
        self.per_page = per_page
        if self.per_page is None:
            self.per_page = 50
        self.objects = []
        self.index = -1
        self.last_response = None

    def __iter__(self) -> "Paginator":
        self.index = -1
        return self

    def __len__(self) -> int:
        if self.length is None:
            self._load_page()
        if self.length is None:
            raise ValueError("Object doesn't provide length")
        return self.length

    @property
    def length(self) -> Optional[int]:
        raise NotImplementedError()

    @property
    def more(self) -> bool:
        raise NotImplementedError()

    @property
    def cursor(self) -> Optional[str]:
        raise NotImplementedError()

    def convert_objects(self) -> List[Any]:
        raise NotImplementedError()

    def update_variables(self) -> None:
        self.variables.update({"perPage": self.per_page, "cursor": self.cursor})

    def _load_page(self) -> bool:
        if not self.more:
            return False
        self.update_variables()
        self.last_response = self.client.execute(
            self.QUERY, variable_values=self.variables
        )
        self.objects.extend(self.convert_objects())
        return True

    def __getitem__(self, index: int) -> Any:
        loaded = True
        while loaded and index > len(self.objects) - 1:
            loaded = self._load_page()
        return self.objects[index]

    def __next__(self) -> Any:
        self.index += 1
        if len(self.objects) <= self.index:
            if not self._load_page():
                raise StopIteration
            if len(self.objects) <= self.index:
                raise StopIteration
        return self.objects[self.index]

    next = __next__


class Project(Attrs):
    """A project is a namespace for runs."""

    def __init__(
        self,
        client: RetryingClient,
        entity: Union[Entity, str],
        name: str,
        attrs: Optional[Dict] = None,
    ) -> None:
        attrs = attrs or {}
        super(Project, self).__init__(dict(attrs))
        self.client = client
        if isinstance(entity, str):
            entity = Entity(client=client, name=entity)
        self.entity = entity
        self.name = name

    @property
    def path(self) -> List[str]:
        return [self.entity.name, self.name]

    def __repr__(self) -> str:
        return "<Project {}/{}>".format(*self.path)

    def runs(
        self,
        filter: Optional[Union[str, Dict]] = None,
        order: str = "-created_at",
        per_page: int = 50,
    ) -> "Runs":
        return Runs(
            client=self.client,
            project=self,
            filters=filter,
            order=order,
            per_page=per_page,
        )

    def run(self, run_id: str) -> "Run":
        return Run(client=self.client, project=self, run_id=run_id)

    def sweeps(self) -> "Sweeps":
        return Sweeps(client=self.client, project=self)

    def create_run(self, run_id: Optional[str] = None) -> "Run":
        """Create a run for the given project"""
        run_id = run_id or util.generate_id()
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
        variables = {"entity": self.entity.name, "project": self.name, "name": run_id}
        res = self.client.execute(mutation, variable_values=variables)
        res = res["upsertBucket"]["bucket"]
        return Run(
            self.client,
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

    def reports(
        self, names: Optional[Union[List[str], str]] = None, per_page: int = 50
    ) -> "Reports":
        return Reports(client=self.client, project=self, names=names, per_page=per_page)

    def report(self, name: str) -> "Report":
        return Reports(client=self.client, project=self, names=[name])[0]

    def delete_run(self, run_id: str, delete_artifacts: bool = False) -> bool:
        return self.run(run_id).delete(delete_artifacts=delete_artifacts)

    def artifact(self, name: str) -> "Artifact":
        return Artifact(client=self.client, project=self, name=name)

    @normalize_exceptions
    def artifacts_types(self) -> "ProjectArtifactTypes":
        return ProjectArtifactTypes(client=self.client, project=self, name=self.name)

    def delete_artifact(self, artifact_name: str) -> bool:
        return Artifact(client=self.client, project=self, name=artifact_name).delete()

    def get_expected_artifact_type(self, artifact_name: str) -> Optional[str]:
        """Returns the expected type for a given artifact name"""
        query = gql(
            """
        query Artifact(
            $entityName: String!,
            $projectName: String!,
            $name: String!
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifact(name: $name) {
                    artifactType {
                        name
                    }
                }
            }
        }
        """
        )
        if ":" not in artifact_name:
            artifact_name += ":latest"

        response = self.client.execute(
            query,
            variable_values={
                "entityName": self.entity.name,
                "projectName": self.name,
                "name": artifact_name,
            },
        )
        return (
            response.get("project", {})
            .get("artifact", {})
            .get("artifactType", {})
            .get("name", None)
        )

    def sync_tensorboard(self, root_dir: str, run_id: Optional[str] = None) -> "Run":
        from wandb.sync import SyncManager  # noqa: F401

        run_id = run_id or util.generate_id()
        sm = SyncManager(
            project=self.name,
            entity=self.entity.name,
            run_id=run_id,
            mark_synced=False,
            app_url=self.client.app_url,
            view=False,
            verbose=False,
            sync_tensorboard=True,
        )
        sm.add(root_dir)
        sm.start()
        while not sm.is_done():
            _ = sm.poll()
        return self.run(run_id=run_id)

    def sweep(self, sweep_id: str) -> "Sweep":
        return Sweep(self.client, project=self, sweep_id=sweep_id)


class Projects(Paginator):
    """
    An iterable collection of `Project` objects.
    """

    QUERY = gql(
        """
        query Projects($entity: String, $cursor: String, $perPage: Int = 50) {
            models(entityName: $entity, after: $cursor, first: $perPage) {
                edges {
                    node {
                        ...ProjectFragment
                    }
                    cursor
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
        %s
        """
        % PROJECT_FRAGMENT
    )

    def __init__(
        self, client: RetryingClient, entity: Union[str, Entity], per_page: int = 50
    ) -> None:
        if isinstance(entity, str):
            entity = Entity(client=client, name=entity)
        self.entity = entity
        variables = {
            "entity": self.entity.name,
        }
        super(Projects, self).__init__(client, variables, per_page)

    @property
    def length(self) -> int:
        if self.last_response:
            return self.last_response["models"]["edges"]
        else:
            return len(list(self))  # TODO(frz)

    @property
    def more(self) -> bool:
        if self.last_response:
            return self.last_response["models"]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self) -> Optional[str]:
        if self.last_response:
            return self.last_response["models"]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self) -> List[Project]:
        return [
            Project(self.client, self.entity, p["node"]["name"], p["node"])
            for p in self.last_response["models"]["edges"]
        ]

    def __repr__(self) -> str:
        return "<Projects {}>".format(self.entity)


class Runs(Paginator):
    """An iterable collection of runs associated with a project and optional filter.
    This is generally used indirectly via the `Api`.runs method
    """

    QUERY = gql(
        """
        query Runs($project: String!, $entity: String!, $cursor: String, $perPage: Int = 50, $order: String, $filters: JSONString) {
            project(name: $project, entityName: $entity) {
                runCount(filters: $filters)
                readOnly
                runs(filters: $filters, after: $cursor, first: $perPage, order: $order) {
                    edges {
                        node {
                            ...RunFragment
                        }
                        cursor
                    }
                    pageInfo {
                        endCursor
                        hasNextPage
                    }
                }
            }
        }
        %s
        """
        % RUN_FRAGMENT
    )

    SWEEP_QUERY = gql(
        """
    query Sweep($project: String!, $entity: String, $sweep_id: String!, $cursor: String, $perPage: Int = 50, $order: String, $filters: JSONString) {
        project(name: $project, entityName: $entity) {
            sweep(sweepName: $sweep_id) {
                runCount(filters: $filters)
                runs(filters: $filters, after: $cursor, first: $perPage, order: $order) {
                    edges {
                        node {
                            ...RunFragment
                        }
                        cursor
                    }
                    pageInfo {
                        endCursor
                        hasNextPage
                    }
                }
            }
        }
    }
    %s
    """
        % RUN_FRAGMENT
    )

    def __init__(
        self,
        client: RetryingClient,
        project: Project,
        sweep_id: Optional[str] = None,
        filters: Optional[Union[str, Dict]] = None,
        order: Optional[str] = None,
        per_page: int = 50,
    ) -> None:
        self.entity = project.entity
        self.project = project
        if filters is None:
            filters = {}
        elif isinstance(filters, str):
            filters = parse_filter(filters)
        self.filters = filters
        self.order = order
        self._sweeps = {}
        self._sweep_id = None
        variables = {
            "project": self.project.name,
            "entity": self.entity.name,
            "order": self.order,
            "filters": json.dumps(self.filters),
        }
        if sweep_id:
            self.QUERY = self.SWEEP_QUERY
            self.variables["sweep_id"] = sweep_id
        super(Runs, self).__init__(client, variables, per_page)

    @property
    def length(self) -> Optional[int]:
        if self.last_response:
            if self._sweep_id:
                return self.last_response["project"]["sweep"]["runCount"]
            return self.last_response["project"]["runCount"]
        else:
            return None

    @property
    def more(self) -> bool:
        if self.last_response:
            if self._sweep_id:
                return self.last_response["project"]["sweep"]["runs"]["pageInfo"][
                    "hasNextPage"
                ]
            return self.last_response["project"]["runs"]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self) -> Optional[str]:
        if self.last_response:
            if self._sweep_id:
                return self.last_response["project"]["sweep"]["runs"]["edges"][-1][
                    "cursor"
                ]
            return self.last_response["project"]["runs"]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self) -> List["Run"]:
        objs = []
        if self.last_response is None or self.last_response.get("project") is None:
            raise ValueError("Could not find project %s" % self.project)
        if self._sweep_id:
            run_responses = self.last_response["project"]["sweep"]["runs"]["edges"]
        else:
            run_responses = self.last_response["project"]["runs"]["edges"]
        for run_response in run_responses:
            run = Run(
                self.client,
                self.entity,
                self.project,
                run_response["node"]["name"],
                run_response["node"],
            )
            objs.append(run)

            if run.sweep_name:
                if run.sweep_name in self._sweeps:
                    sweep = self._sweeps[run.sweep_name]
                else:
                    sweep = Sweep(
                        client=self.client,
                        project=self.project,
                        sweep_id=run.sweep_name,
                    )
                    self._sweeps[run.sweep_name] = sweep

                if sweep is None:
                    continue
                run.sweep = sweep
        return objs

    def __repr__(self) -> str:
        return "<Runs {}/{} ({})>".format(self.entity, self.project, len(self))


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
    """

    QUERY = gql(
        """
    query Sweep($project: String!, $entity: String, $name: String!) {
        project(name: $project, entityName: $entity) {
            sweep(sweepName: $name) {
                id
                name
                bestLoss
                config
            }
        }
    }
    """
    )

    def __init__(
        self,
        client: RetryingClient,
        project: Project,
        sweep_id: str,
        attrs: Optional[Dict] = None,
    ) -> None:
        # TODO: Add agents / flesh this out.
        super(Sweep, self).__init__(attrs)
        self.client = client
        self.entity = project.entity
        self.project = project
        self.id = sweep_id
        if not attrs:
            self._load()

    def _load(self) -> None:
        response = self.client.execute(
            self.QUERY,
            {"entity": self.entity.name, "project": self.project.name, "name": self.id},
        )
        sweep_resp = response.get("project", {}).get("sweep")
        if not sweep_resp:
            raise ValueError("Could not find sweep %s" % self.path)
        self._attrs.update(sweep_resp)

    @property
    def config(self) -> dict:
        return yaml.load(self._attrs["config"])

    @property
    def order(self) -> str:
        if self._attrs.get("config") and self.config.get("metric"):
            sort_order = self.config["metric"].get("goal", "minimize")
            prefix = "+" if sort_order == "minimize" else "-"
            return QueryGenerator.format_order_key(
                prefix + self.config["metric"]["name"]
            )

    def best_run(self, order: Optional[str] = None) -> Optional["Run"]:
        "Returns the best run sorted by the metric defined in config or the order passed in"
        if order is None:
            order = self.order
        else:
            order = QueryGenerator.format_order_key(order)
        if order is None:
            wandb.termwarn(
                "No order specified and couldn't find metric in sweep config, returning most recent run"
            )
        else:
            wandb.termlog("Sorting runs by %s" % order)
        filters = {"$and": [{"sweep": self.id}]}
        try:
            return Runs(
                client=self.client,
                project=self.project,
                order=order,
                filters=filters,
                per_page=1,
            )[0]
        except IndexError:
            return None

    @property
    def path(self) -> List[str]:
        return [
            urllib.parse.quote_plus(self.entity.name),
            urllib.parse.quote_plus(self.project.name),
            urllib.parse.quote_plus(self.id),
        ]

    @property
    def url(self) -> str:
        path = self.path
        path.insert(2, "sweeps")
        return self.client.app_url + "/".join(path)

    def runs(
        self, filters: Optional[Union[str, Dict]] = None, order: Optional[str] = None
    ):
        if order is None:
            order = self.order
        return Runs(
            client=self.client,
            project=self.project,
            sweep_id=self.id,
            order=order,
            filters=filters,
        )

    def __repr__(self) -> str:
        return "<Sweep {}>".format("/".join(self.path))


class QueryGenerator(object):
    """QueryGenerator is a helper object to write filters for runs"""

    INDIVIDUAL_OP_TO_MONGO = {
        "!=": "$ne",
        ">": "$gt",
        ">=": "$gte",
        "<": "$lt",
        "<=": "$lte",
        "IN": "$in",
        "NIN": "$nin",
        "REGEX": "$regex",
    }

    GROUP_OP_TO_MONGO = {"AND": "$and", "OR": "$or"}

    @classmethod
    def format_order_key(cls, key: str) -> str:
        if key.startswith("+") or key.startswith("-"):
            direction = key[0]
            key = key[1:]
        else:
            direction = "-"
        parts = key.split(".")
        if len(parts) == 1:
            # Assume the user meant summary_metrics if not a run column
            if parts[0] not in ["createdAt", "updatedAt", "name", "sweep"]:
                return direction + "summary_metrics." + parts[0]
        # Assume summary metrics if prefix isn't known
        elif parts[0] not in ["config", "summary_metrics", "tags"]:
            return direction + ".".join(["summary_metrics"] + parts)
        else:
            return direction + ".".join(parts)

    def _is_group(self, op: Dict) -> bool:
        return op.get("filters") is not None

    def _is_individual(self, op: Dict) -> bool:
        return op.get("key") is not None

    def _to_mongo_op_value(self, op: str, value: Any) -> Any:
        if op == "=":
            return value
        else:
            return {self.INDIVIDUAL_OP_TO_MONGO[op]: value}

    def key_to_server_path(self, key: str) -> str:
        if key["section"] == "config":
            return "config." + key["name"]
        elif key["section"] == "summary":
            return "summary_metrics." + key["name"]
        elif key["section"] == "keys_info":
            return "keys_info.keys." + key["name"]
        elif key["section"] == "run":
            return key["name"]
        elif key["section"] == "tags":
            return "tags." + key["name"]
        raise ValueError("Invalid key: %s" % key)

    def _to_mongo_individual(self, filter: Dict) -> Any:
        if filter["key"]["name"] == "":
            return None

        if filter.get("value") is None and filter["op"] != "=" and filter["op"] != "!=":
            return None

        if filter.get("disabled") is None and filter["disabled"]:
            return None

        if filter["key"]["section"] == "tags":
            if filter["op"] == "IN":
                return {"tags": {"$in": filter["value"]}}
            if filter["value"] is False:
                return {
                    "$or": [{"tags": None}, {"tags": {"$ne": filter["key"]["name"]}}]
                }
            else:
                return {"tags": filter["key"]["name"]}
        path = self.key_to_server_path(filter.key)
        if path is None:
            return path
        return {path: self._to_mongo_op_value(filter["op"], filter["value"])}

    def filter_to_mongo(self, filter: Dict) -> Dict[str, List]:
        if self._is_individual(filter):
            return self._to_mongo_individual(filter)
        elif self._is_group(filter):
            return {
                self.GROUP_OP_TO_MONGO[filter["op"]]: [
                    self.filter_to_mongo(f) for f in filter["filters"]
                ]
            }


class User(Attrs):
    def init(self, attrs: Optional[Dict]) -> None:
        super(User, self).__init__(attrs)


class Run(Attrs):
    """
    A single run associated with an entity and project.

    Attributes:
        tags ([str]): a list of tags associated with the run
        url (str): the url of this run
        id (str): unique identifier for the run (defaults to eight characters)
        name (str): the name of the run
        state (str): one of: running, finished, crashed, aborted
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
    """

    def __init__(
        self,
        client: RetryingClient,
        entity: Optional[Union[str, Entity]] = None,
        project: Optional[Union[str, Project]] = None,
        run_id: Optional[str] = None,
        attrs: Optional[Dict] = None,
    ):
        """
        Run is always initialized by calling api.runs() where api is an instance of wandb.Api
        """
        attrs = attrs or {}
        super(Run, self).__init__(dict(attrs))
        self.client = client
        if entity is None:
            if project is None or not isinstance(project, Project):
                raise ValueError("Invalid project: {}/{}".format(entity, project))
            entity = project.entity
        elif isinstance(entity, str):
            entity = Entity(client=client, name=entity)
        if isinstance(project, str):
            project = entity.project(name=project)
        self.entity = entity
        self.project = project
        self._files = {}
        self._base_dir = env.get_dir(tempfile.gettempdir())
        self.id = run_id
        self.sweep = None
        self.dir = os.path.join(self._base_dir, *self.path)
        try:
            os.makedirs(self.dir)
        except OSError:
            pass
        self._summary = None
        self.state = attrs.get("state", "not found")
        if not attrs:
            self._load()

    @property
    def storage_id(self) -> str:
        # For compatibility with wandb.Run, which has storage IDs
        # in self.storage_id and names in self.id.

        return self._attrs.get("id")

    @property
    def id(self) -> str:
        return self._attrs.get("name")

    @id.setter
    def id(self, new_id: str) -> None:
        attrs = self._attrs
        attrs["name"] = new_id

    @property
    def name(self) -> str:
        return self._attrs.get("displayName")

    @name.setter
    def name(self, new_name: str) -> str:
        self._attrs["displayName"] = new_name

    def _load(self) -> dict:
        query = gql(
            """
        query Run($project: String!, $entity: String!, $name: String!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) {
                    ...RunFragment
                }
            }
        }
        %s
        """
            % RUN_FRAGMENT
        )
        response = self._exec(query)
        if (
            response is None
            or response.get("project") is None
            or response["project"].get("run") is None
        ):
            raise ValueError("Could not find run %s" % self)
        self._attrs = response["project"]["run"]
        self.state = self._attrs["state"]

        if self.sweep_name:
            # There may be a lot of runs. Don't bother pulling them all
            # just for the sake of this one.
            self.sweep = Sweep.get(
                client=self.client,
                entity=self.entity,
                project=self.project,
                sweep_id=self.sweep_name,
            )

        self._attrs["summaryMetrics"] = (
            json.loads(self._attrs["summaryMetrics"])
            if self._attrs.get("summaryMetrics")
            else {}
        )
        self._attrs["systemMetrics"] = (
            json.loads(self._attrs["systemMetrics"])
            if self._attrs.get("systemMetrics")
            else {}
        )
        if self._attrs.get("user"):
            self.user = User(self._attrs["user"])
        config_user, config_raw = {}, {}
        for key, value in six.iteritems(json.loads(self._attrs.get("config") or "{}")):
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
    def update(self) -> None:
        """
        Persists changes to the run object to the wandb backend.
        """
        mutation = gql(
            """
        mutation UpsertBucket($id: String!, $description: String, $display_name: String, $notes: String, $tags: [String!], $config: JSONString!, $groupName: String) {
            upsertBucket(input: {id: $id, description: $description, displayName: $display_name, notes: $notes, tags: $tags, config: $config, groupName: $groupName}) {
                bucket {
                    ...RunFragment
                }
            }
        }
        %s
        """
            % RUN_FRAGMENT
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
    def delete(self, delete_artifacts: bool = False) -> None:
        """
        Deletes the given run from the wandb backend.
        """
        mutation = gql(
            """
            mutation DeleteRun(
                $id: ID!,
                %s
            ) {
                deleteRun(input: {
                    id: $id,
                    %s
                }) {
                    clientMutationId
                }
            }
        """
            %
            # Older backends might not support the 'deleteArtifacts' argument,
            # so only supply it when it is explicitly set.
            (
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

    def save(self) -> None:
        self.update()

    @property
    def json_config(self) -> str:
        config = {}
        for k, v in six.iteritems(self.config):
            config[k] = {"value": v, "desc": None}
        return json.dumps(config)

    def _exec(self, query: Document, **kwargs) -> ExecutionResult:
        """Execute a query against the cloud backend"""
        variables = {
            "entity": self.entity.name,
            "project": self.project.name,
            "name": self.id,
        }
        variables.update(kwargs)
        return self.client.execute(query, variable_values=variables)

    def _sampled_history(
        self, keys: List[str], x_axis: str = "_step", samples: int = 500
    ) -> List[Dict]:
        spec = {"keys": [x_axis] + keys, "samples": samples}
        query = gql(
            """
        query Run($project: String!, $entity: String!, $name: String!, $specs: [JSONString!]!) {
            project(name: $project, entityName: $entity) {
                run(name: $name) { sampledHistory(specs: $specs) }
            }
        }
        """
        )

        response = self._exec(query, specs=[json.dumps(spec)])
        # sampledHistory returns one list per spec, we only send one spec
        return response["project"]["run"]["sampledHistory"][0]

    def _full_history(self, samples: int = 500, stream: str = "default") -> List[Dict]:
        node = "history" if stream == "default" else "events"
        query = gql(
            """
        query Run($project: String!, $entity: String!, $name: String!, $samples: Int) {
            project(name: $project, entityName: $entity) {
                run(name: $name) { %s(samples: $samples) }
            }
        }
        """
            % node
        )

        response = self._exec(query, samples=samples)
        return [json.loads(line) for line in response["project"]["run"][node]]

    @normalize_exceptions
    def files(self, names: Optional[List[str]] = None, per_page: int = 50) -> "Files":
        """
        Arguments:
            names (list): names of the requested files, if empty returns all files
            per_page (int): number of results per page

        Returns:
            A `Files` object, which is an iterator over `File` obejcts.
        """
        names = names or []
        return Files(self.client, self, names, per_page)

    @normalize_exceptions
    def file(self, name: str) -> "File":
        """
        Arguments:
            name (str): name of requested file.

        Returns:
            A `File` matching the name argument.
        """
        return Files(self.client, self, [name])[0]

    @normalize_exceptions
    def upload_file(self, path: str, root: str = ".") -> "File":
        """
        Arguments:
            path (str): name of file to upload.
            root (str): the root path to save the file relative to.  i.e.
                If you want to have the file saved in the run as "my_dir/file.txt"
                and you're currently in "my_dir" you would set root to "../"

        Returns:
            A `File` matching the name argument.
        """
        api = InternalApi(
            default_settings={"entity": self.entity.name, "project": self.project.name},
            retry_timedelta=RETRY_TIMEDELTA,
        )
        api.set_current_run_id(self.id)
        root = os.path.abspath(root)
        name = os.path.relpath(path, root)
        with open(os.path.join(root, name), "rb") as f:
            api.push({util.to_forward_slash_path(name): f})
        return Files(self.client, self, [name])[0]

    @normalize_exceptions
    def history(
        self,
        samples: int = 500,
        keys: Optional[List[str]] = None,
        x_axis: str = "_step",
        pandas: bool = True,
        stream: str = "default",
    ) -> Any:
        """
        Returns sampled history metrics for a run.  This is simpler and faster if you are ok with
        the history records being sampled.

        Arguments:
            samples (int, optional): The number of samples to return
            pandas (bool, optional): Return a pandas dataframe
            keys (list, optional): Only return metrics for specific keys
            x_axis (str, optional): Use this metric as the xAxis defaults to _step
            stream (str, optional): "default" for metrics, "system" for machine metrics

        Returns:
            If pandas=True returns a `pandas.DataFrame` of history metrics.
            If pandas=False returns a list of dicts of history metrics.
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
            pandas = util.get_module("pandas")
            if pandas:
                lines = pandas.DataFrame.from_records(lines)
            else:
                print("Unable to load pandas, call history with pandas=False")
        return lines

    @normalize_exceptions
    def scan_history(
        self,
        keys: Optional[List[str]] = None,
        page_size: int = 1000,
        min_step: Optional[int] = None,
        max_step: Optional[int] = None,
    ) -> Union[List, "HistoryScan", "SampledHistoryScan"]:
        """
        Returns an iterable collection of all history records for a run.

        Example:
            Export all the loss values for an example run

            ```python
            run = api.run("l2k2/examples-numpy-boston/i0wt6xua")
            history = run.scan_history(keys=["Loss"])
            losses = [row["Loss"] for row in history]
            ```


        Arguments:
            keys ([str], optional): only fetch these keys, and only fetch rows that have all of keys defined.
            page_size (int, optional): size of pages to fetch from the api

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
            return HistoryScan(
                run=self,
                client=self.client,
                page_size=page_size,
                min_step=min_step,
                max_step=max_step,
            )
        else:
            return SampledHistoryScan(
                run=self,
                client=self.client,
                keys=keys,
                page_size=page_size,
                min_step=min_step,
                max_step=max_step,
            )

    @normalize_exceptions
    def logged_artifacts(self, per_page: int = 100) -> "RunArtifacts":
        return RunArtifacts(self.client, self, mode="logged", per_page=per_page)

    @normalize_exceptions
    def used_artifacts(self, per_page: int = 100) -> "RunArtifacts":
        return RunArtifacts(self.client, self, mode="used", per_page=per_page)

    @normalize_exceptions
    def use_artifact(self, artifact: "Artifact") -> None:
        """ Declare an artifact as an input to a run.

        Arguments:
            artifact (`Artifact`): An artifact returned from
                `wandb.Api().artifact(name)`
        Returns:
            A `Artifact` object.
        """
        api = InternalApi(
            default_settings={"entity": self.entity.name, "project": self.project.name},
            retry_timedelta=RETRY_TIMEDELTA,
        )
        api.set_current_run_id(self.id)

        if isinstance(artifact, Artifact):
            api.use_artifact(artifact.id)
        elif isinstance(artifact, wandb.Artifact):
            raise ValueError(
                "Only existing artifacts are accepted by this api. "
                "Manually create one with `wandb artifacts put`"
            )
        else:
            raise ValueError("You must pass a wandb.Api().artifact() to use_artifact")

    @normalize_exceptions
    def log_artifact(
        self, artifact: "Artifact", aliases: Optional[List[str]] = None
    ) -> None:
        """ Declare an artifact as output of a run.

        Arguments:
            artifact (`Artifact`): An artifact returned from
                `wandb.Api().artifact(name)`
            aliases (list, optional): Aliases to apply to this artifact
        Returns:
            A `Artifact` object.
        """
        api = InternalApi(
            default_settings={"entity": self.entity.name, "project": self.project.name},
            retry_timedelta=RETRY_TIMEDELTA,
        )
        api.set_current_run_id(self.id)

        if isinstance(artifact, Artifact):
            artifact_collection_name = artifact.name.split(":")[0]
            api.create_artifact(
                artifact.type,
                artifact_collection_name,
                artifact.digest,
                aliases=aliases,
            )
        elif isinstance(artifact, wandb.Artifact):
            raise ValueError(
                "Only existing artifacts are accepted by this api. "
                "Manually create one with `wandb artifacts put`"
            )
        else:
            raise ValueError("You must pass a wandb.Api().artifact() to use_artifact")

    @property
    def summary(self) -> HTTPSummary:
        if self._summary is None:
            # TODO: fix the outdir issue
            self._summary = HTTPSummary(self, self.client, summary=self.summary_metrics)
        return self._summary

    @property
    def path(self) -> List[str]:
        return [
            urllib.parse.quote_plus(self.entity.name),
            urllib.parse.quote_plus(self.project.name),
            urllib.parse.quote_plus(self.id),
        ]

    @property
    def url(self) -> str:
        path = self.path
        path.insert(2, "runs")
        return self.client.app_url + "/".join(path)

    @property
    def lastHistoryStep(self) -> int:  # noqa: N802
        query = gql(
            """
        query Run($project: String!, $entity: String!, $name: String!) {
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

    def __repr__(self) -> str:
        return "<Run {} ({})>".format("/".join(self.path), self.state)


class Files(Paginator):
    """An iterable collection of `File` objects."""

    QUERY = gql(
        """
        query Run($project: String!, $entity: String!, $name: String!, $fileCursor: String,
            $fileLimit: Int = 50, $fileNames: [String] = [], $upload: Boolean = false) {
            project(name: $project, entityName: $entity) {
                run(name: $name) {
                    fileCount
                    ...RunFilesFragment
                }
            }
        }
        %s
        """
        % FILE_FRAGMENT
    )

    def __init__(
        self,
        client: RetryingClient,
        run: Run,
        names: Optional[List[str]] = None,
        per_page: int = 50,
        upload: bool = False,
    ) -> None:
        self.run = run
        variables = {
            "project": run.project.name,
            "entity": run.entity.name,
            "name": run.id,
            "fileNames": names or [],
            "upload": upload,
        }
        super(Files, self).__init__(client, variables, per_page)

    @property
    def length(self) -> Optional[int]:
        if self.last_response:
            return self.last_response["project"]["run"]["fileCount"]
        else:
            return None

    @property
    def more(self) -> bool:
        if self.last_response:
            return self.last_response["project"]["run"]["files"]["pageInfo"][
                "hasNextPage"
            ]
        else:
            return True

    @property
    def cursor(self) -> Optional[str]:
        if self.last_response:
            return self.last_response["project"]["run"]["files"]["edges"][-1]["cursor"]
        else:
            return None

    def update_variables(self) -> None:
        self.variables.update({"fileLimit": self.per_page, "fileCursor": self.cursor})

    def convert_objects(self) -> List["File"]:
        return [
            File(self.client, r["node"])
            for r in self.last_response["project"]["run"]["files"]["edges"]
        ]

    def __repr__(self) -> str:
        return "<Files {} ({})>".format("/".join(self.run.path), len(self))


class File(Attrs):
    """File is a class associated with a file saved by wandb.

    Attributes:
        name (string): filename
        url (string): path to file
        direct_url (string): path to file in the bucket
        md5 (string): md5 of file
        mimetype (string): mimetype of file
        updated_at (string): timestamp of last update
        size (int): size of file in bytes

    """

    def __init__(self, client: RetryingClient, attrs: Optional[Dict] = None):
        super(File, self).__init__(attrs)
        self.client = client

    @property
    def size(self) -> int:
        size_bytes = self._attrs["sizeBytes"]
        if size_bytes is not None:
            return int(size_bytes)
        return 0

    @normalize_exceptions
    @retry.retriable(
        retry_timedelta=RETRY_TIMEDELTA,
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException),
    )
    def download(self, root: str = ".", replace: bool = False) -> IO:
        """Downloads a file previously saved by a run from the wandb server.

        Arguments:
            replace (boolean): If `True`, download will overwrite a local file
                if it exists. Defaults to `False`.
            root (str): Local directory to save the file.  Defaults to ".".

        Raises:
            `ValueError` if file already exists and replace=False
        """
        path = os.path.join(root, self.name)
        if os.path.exists(path) and not replace:
            raise ValueError("File already exists, pass replace=True to overwrite")
        util.download_file_from_url(path, self.url, Api().api_key)
        return open(path, "r")

    @normalize_exceptions
    def delete(self) -> None:
        mutation = gql(
            """
        mutation deleteFiles($files: [ID!]!) {
            deleteFiles(input: {
                files: $files
            }) {
                success
            }
        }
        """
        )
        self.client.execute(mutation, variable_values={"files": [self.id]})

    def __repr__(self) -> str:
        return "<File {} ({}) {}>".format(
            self.name,
            self.mimetype,
            util.to_human_size(self.size, units=util.POW_2_BYTES),
        )


class ArtifactType(Attrs):
    def __init__(
        self,
        client: RetryingClient,
        project: Project,
        type_name: str,
        attrs: Optional[Dict] = None,
    ) -> None:
        super(ArtifactType, self).__init__(attrs)
        self.client = client
        self.entity = project.entity
        self.project = project
        self.type = type_name
        if not attrs:
            self._load()

    def _load(self) -> None:
        query = gql(
            """
        query ProjectArtifactType(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    id
                    name
                    description
                    createdAt
                }
            }
        }
        """
        )
        response = self.client.execute(
            query,
            variable_values={
                "entityName": self.entity.name,
                "projectName": self.project.name,
                "artifactTypeName": self.type,
            },
        )
        if response is None or response.get("project", {}).get("artifactType") is None:
            raise ValueError("Could not find artifact type %s" % self.type)
        self._attrs = response["project"]["artifactType"]

    @property
    def id(self) -> str:
        return self._attrs["id"]

    @property
    def name(self) -> str:
        return self._attrs["name"]

    @normalize_exceptions
    def collections(self, per_page: int = 50) -> "ProjectArtifactCollections":
        """Artifact collections"""
        return ProjectArtifactCollections(
            self.client, self.entity, self.project, self.type
        )

    def collection(self, name: str) -> "ArtifactCollection":
        return ArtifactCollection(
            self.client, self.entity, self.project, name, self.type
        )

    def __repr__(self) -> str:
        return "<ArtifactType {}>".format(self.type)


class ProjectArtifactTypes(Paginator):
    QUERY = gql(
        """
        query ProjectArtifacts(
            $entityName: String!,
            $projectName: String!,
            $cursor: String,
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactTypes(after: $cursor) {
                    ...ArtifactTypesFragment
                }
            }
        }
        %s
    """
        % ARTIFACTS_TYPES_FRAGMENT
    )

    def __init__(
        self,
        client: RetryingClient,
        project: Project,
        name: Optional[str] = None,
        per_page: int = 50,
    ) -> None:
        self.entity = project.entity
        self.project = project

        variable_values = {
            "entityName": project.entity.name,
            "projectName": project.name,
        }

        super(ProjectArtifactTypes, self).__init__(client, variable_values, per_page)

    @property
    def length(self) -> Optional[int]:
        # TODO
        return None

    @property
    def more(self) -> bool:
        if self.last_response:
            return self.last_response["project"]["artifactTypes"]["pageInfo"][
                "hasNextPage"
            ]
        else:
            return True

    @property
    def cursor(self) -> Optional[str]:
        if self.last_response:
            return self.last_response["project"]["artifactTypes"]["edges"][-1]["cursor"]
        else:
            return None

    def update_variables(self):
        self.variables.update({"cursor": self.cursor})

    def convert_objects(self) -> List[ArtifactType]:
        if self.last_response["project"] is None:
            return []
        return [
            ArtifactType(
                self.client, self.entity, self.project, r["node"]["name"], r["node"]
            )
            for r in self.last_response["project"]["artifactTypes"]["edges"]
        ]


class ArtifactCollection(Attrs):
    def __init__(
        self,
        client: RetryingClient,
        project: Project,
        name: str,
        type: str,
        attrs: Optional[Dict] = None,
    ) -> None:
        super(ArtifactCollection, self).__init__(attrs)
        self.client = client
        self.entity = project.entity
        self.project = project
        self.name = name
        self.type = type
        self._attrs = attrs

    @property
    def id(self) -> str:
        return self._attrs["id"]

    @normalize_exceptions
    def versions(self) -> "ArtifactVersions":
        """Artifact versions"""
        return ArtifactVersions(
            client=self.client,
            project=self.project,
            collection_name=self.name,
            type=self.type,
        )

    def __repr__(self) -> str:
        return "<ArtifactCollection {} ({})>".format(self.name, self.type)


class ProjectArtifactCollections(Paginator):
    QUERY = gql(
        """
        query ProjectArtifactCollections(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!
            $cursor: String,
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    artifactSequences(after: $cursor) {
                        pageInfo {
                            endCursor
                            hasNextPage
                        }
                        totalCount
                        edges {
                            node {
                                id
                                name
                                description
                                createdAt
                            }
                        }
                    }
                }
            }
        }
    """
    )

    def __init__(
        self,
        client: RetryingClient,
        project: Project,
        type_name: str,
        per_page: int = 50,
    ) -> None:
        self.entity = project.entity
        self.project = project
        self.type_name = type_name

        variable_values = {
            "entityName": project.entity.name,
            "projectName": project.name,
            "artifactTypeName": type_name,
        }

        super(ProjectArtifactCollections, self).__init__(
            client, variable_values, per_page
        )

    @property
    def length(self) -> Optional[int]:
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactSequences"][
                "totalCount"
            ]
        else:
            return None

    @property
    def more(self) -> bool:
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactSequences"][
                "pageInfo"
            ]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self) -> Optional[str]:
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactSequences"][
                "edges"
            ][-1]["cursor"]
        else:
            return None

    def update_variables(self) -> None:
        self.variables.update({"cursor": self.cursor})

    def convert_objects(self) -> List[ArtifactCollection]:
        return [
            ArtifactCollection(
                self.client,
                self.entity,
                self.project,
                r["node"]["name"],
                self.type_name,
                r["node"],
            )
            for r in self.last_response["project"]["artifactType"]["artifactSequences"][
                "edges"
            ]
        ]


class RunArtifacts(Paginator):
    OUTPUT_QUERY = gql(
        """
        query RunArtifacts(
            $entity: String!, $project: String!, $runName: String!, $cursor: String,
        ) {
            project(name: $project, entityName: $entity) {
                run(name: $runName) {
                    outputArtifacts(after: $cursor) {
                        totalCount
                        edges {
                            node {
                                ...ArtifactFragment
                            }
                            cursor
                        }
                        pageInfo {
                            endCursor
                            hasNextPage
                        }
                    }
                }
            }
        }
        %s
    """
        % ARTIFACT_FRAGMENT
    )

    INPUT_QUERY = gql(
        """
        query RunArtifacts(
            $entity: String!, $project: String!, $runName: String!, $cursor: String,
        ) {
            project(name: $project, entityName: $entity) {
                run(name: $runName) {
                    inputArtifacts(after: $cursor) {
                        totalCount
                        edges {
                            node {
                                ...ArtifactFragment
                            }
                            cursor
                        }
                        pageInfo {
                            endCursor
                            hasNextPage
                        }
                    }
                }
            }
        }
        %s
    """
        % ARTIFACT_FRAGMENT
    )

    def __init__(
        self, client: RetryingClient, run: Run, mode: str = "logged", per_page: int = 50
    ) -> None:
        self.run = run
        if mode == "logged":
            self.run_key = "outputArtifacts"
            self.QUERY = self.OUTPUT_QUERY
        elif mode == "used":
            self.run_key = "inputArtifacts"
            self.QUERY = self.INPUT_QUERY
        else:
            raise ValueError("mode must be logged or used")

        variable_values = {
            "entity": run.entity.name,
            "project": run.project.name,
            "runName": run.id,
        }

        super(RunArtifacts, self).__init__(client, variable_values, per_page)

    @property
    def length(self) -> Optional[int]:
        if self.last_response:
            return self.last_response["project"]["run"][self.run_key]["totalCount"]
        else:
            return None

    @property
    def more(self) -> bool:
        if self.last_response:
            return self.last_response["project"]["run"][self.run_key]["pageInfo"][
                "hasNextPage"
            ]
        else:
            return True

    @property
    def cursor(self) -> Optional[str]:
        if self.last_response:
            return self.last_response["project"]["run"][self.run_key]["edges"]["cursor"]
        else:
            return None

    def update_variables(self) -> None:
        self.variables.update({"cursor": self.cursor})

    def convert_objects(self) -> List["Artifact"]:
        return [
            Artifact(
                self.client,
                self.run.entity,
                self.run.project,
                r["node"]["digest"],
                r["node"],
            )
            for r in self.last_response["project"]["run"][self.run_key]["edges"]
        ]


class _DownloadedArtifactEntry(artifacts.ArtifactEntry):
    def __init__(
        self, name: str, entry: artifacts.ArtifactEntry, parent_artifact: "Artifact"
    ) -> None:
        self.name = name
        self.entry = entry
        self._parent_artifact = parent_artifact

        # Have to copy over a bunch of variables to get this ArtifactEntry interface
        # to work properly
        self.path = entry.path
        self.ref = entry.ref
        self.digest = entry.digest
        self.birth_artifact_id = entry.birth_artifact_id
        self.size = entry.size
        self.extra = entry.extra
        self.local_path = entry.local_path

    def parent_artifact(self) -> "Artifact":
        return self._parent_artifact

    def copy(self, cache_path: str, target_path: str) -> str:
        # can't have colons in Windows
        if platform.system() == "Windows":
            head, tail = os.path.splitdrive(target_path)
            target_path = head + tail.replace(":", "-")

        need_copy = (
            not os.path.isfile(target_path)
            or os.stat(cache_path).st_mtime != os.stat(target_path).st_mtime
        )
        if need_copy:
            util.mkdir_exists_ok(os.path.dirname(target_path))
            # We use copy2, which preserves file metadata including modified
            # time (which we use above to check whether we should do the copy).
            shutil.copy2(cache_path, target_path)
        return target_path

    def download(self, root: Optional[str] = None) -> str:
        root = root or self._parent_artifact._default_root()
        self._parent_artifact._add_download_root(root)
        manifest = self._parent_artifact._load_manifest()
        if self.entry.ref is not None:
            cache_path = manifest.storage_policy.load_reference(
                self._parent_artifact,
                self.name,
                manifest.entries[self.name],
                local=True,
            )
        else:
            cache_path = manifest.storage_policy.load_file(
                self._parent_artifact, self.name, manifest.entries[self.name]
            )

        return self.copy(cache_path, os.path.join(root, self.name))

    def ref_target(self) -> str:
        manifest = self._parent_artifact._load_manifest()
        if self.entry.ref is not None:
            return manifest.storage_policy.load_reference(
                self._parent_artifact,
                self.name,
                manifest.entries[self.name],
                local=False,
            )
        raise ValueError("Only reference entries support ref_target().")

    def ref_url(self) -> str:
        return (
            "wandb-artifact://"
            + util.b64_to_hex_id(self._parent_artifact.id)
            + "/"
            + self.name
        )


class Artifact(artifacts.Artifact):
    """
    A wandb Artifact.

    An artifact that has been logged, including all its attributes, links to the runs
    that use it, and a link to the run that logged it.

    Examples:
        Basic usage
        ```
        api = wandb.Api()
        artifact = api.artifact('project/artifact:alias')

        # Get information about the artifact...
        artifact.digest
        artifact.aliases
        ```

        Updating an artifact
        ```
        artifact = api.artifact('project/artifact:alias')

        # Update the description
        artifact.description = 'My new description'

        # Selectively update metadata keys
        artifact.metadata["oldKey"] = "new value"

        # Replace the metadata entirely
        artifact.metadata = {"newKey": "new value"}

        # Add an alias
        artifact.aliases.append('best')

        # Remove an alias
        artifact.aliases.remove('latest')

        # Completely replace the aliases
        artifact.aliases = ['replaced']

        # Persist all artifact modifications
        artifact.save()
        ```

        Artifact graph traversal
        ```
        artifact = api.artifact('project/artifact:alias')

        # Walk up and down the graph from an artifact:
        producer_run = artifact.logged_by()
        consumer_runs = artifact.used_by()

        # Walk up and down the graph from a run:
        logged_artifacts = run.logged_artifacts()
        used_artifacts = run.used_artifacts()
        ```

        Deleting an artifact
        ```
        artifact = api.artifact('project/artifact:alias')
        artifact.delete()
        ```
    """

    QUERY = gql(
        """
        query Artifact(
            $id: ID!,
        ) {
            artifact(id: $id) {
                currentManifest {
                    id
                    file {
                        id
                        directUrl
                    }
                }
                ...ArtifactFragment
            }
        }
        %s
    """
        % ARTIFACT_FRAGMENT
    )

    @classmethod
    def from_id(cls, artifact_id: str, client: RetryingClient) -> "Artifact":
        artifact = artifacts.get_artifacts_cache().get_artifact(artifact_id)
        if artifact is not None:
            return artifact
        response = client.execute(Artifact.QUERY, variable_values={"id": artifact_id},)

        name = None
        if response.get("artifact") is not None:
            if response["artifact"].get("aliases") is not None:
                aliases = response["artifact"]["aliases"]
                name = ":".join(
                    [aliases[0]["artifactCollectionName"], aliases[0]["alias"]]
                )
                if len(aliases) > 1:
                    for alias in aliases:
                        if alias["alias"] != "latest":
                            name = ":".join(
                                [alias["artifactCollectionName"], alias["alias"]]
                            )
                            break

            artifact = cls(
                client=client,
                entity=None,
                project=None,
                name=name,
                attrs=response["artifact"],
            )
            index_file_url = response["artifact"]["currentManifest"]["file"][
                "directUrl"
            ]
            with requests.get(index_file_url) as req:
                req.raise_for_status()
                artifact._manifest = artifacts.ArtifactManifest.from_manifest_json(
                    artifact, json.loads(six.ensure_text(req.content))
                )

            artifact._load_dependent_manifests()

            return artifact

    def __init__(
        self,
        client: RetryingClient,
        project: Project,
        name: str,
        attrs: Optional[Dict] = None,
    ) -> None:
        self.client = client
        self.entity = project.entity
        self.project = project
        self._artifact_name = name
        self._attrs = attrs
        if self._attrs is None:
            self._load()
        self.metadata = json.loads(self._attrs.get("metadata") or "{}")
        self.description = self._attrs.get("description", None)
        self._sequence_name = self._attrs["artifactSequence"]["name"]
        self._version_index = self._attrs.get("versionIndex", None)
        self._aliases = [
            a["alias"]
            for a in self._attrs["aliases"]
            if not re.match(r"^v\d+$", a["alias"])
            and a["artifactCollectionName"] == self._sequence_name
        ]
        self._manifest = None
        self._is_downloaded = False
        self._dependent_artifacts = []
        self._download_roots = set()
        artifacts.get_artifacts_cache().store_artifact(self)

    @property
    def id(self) -> str:
        return self._attrs["id"]

    @property
    def version(self) -> str:
        return "v%d" % self._version_index

    @property
    def manifest(self) -> artifacts.ArtifactManifest:
        return self._load_manifest()

    @property
    def digest(self) -> str:
        return self._attrs["digest"]

    @property
    def state(self) -> str:
        return self._attrs["state"]

    @property
    def size(self) -> str:
        return self._attrs["size"]

    @property
    def created_at(self) -> datetime.datetime:
        """
        Returns:
            (datetime): The time at which the artifact was created.
        """
        return self._attrs["createdAt"]

    @property
    def updated_at(self) -> datetime.datetime:
        """
        Returns:
            (datetime): The time at which the artifact was last updated.
        """
        return self._attrs["updatedAt"] or self._attrs["createdAt"]

    @property
    def type(self) -> str:
        return self._attrs["artifactType"]["name"]

    @property
    def commit_hash(self) -> str:
        return self._attrs.get("commitHash", "")

    @property
    def name(self) -> str:
        if self._version_index is None:
            return self.digest
        return "%s:v%s" % (self._sequence_name, self._version_index)

    @property
    def aliases(self) -> List[str]:
        """
        The aliases associated with this artifact.

        Returns:
            List[str]: The aliases associated with this artifact.

        """
        return self._aliases

    @aliases.setter
    def aliases(self, aliases: List[str]) -> None:
        for alias in aliases:
            if any(char in alias for char in ["/", ":"]):
                raise ValueError(
                    'Invalid alias "%s", slashes and colons are disallowed' % alias
                )
        self._aliases = aliases

    @normalize_exceptions
    def delete(self) -> bool:
        """Delete artifact and its files."""
        mutation = gql(
            """
        mutation deleteArtifact($id: ID!) {
            deleteArtifact(input: {artifactID: $id}) {
                artifact {
                    id
                }
            }
        }
        """
        )
        self.client.execute(mutation, variable_values={"id": self.id,})
        return True

    def new_file(self, name: str, mode: Optional[str] = None) -> None:
        raise ValueError("Cannot add files to an artifact once it has been saved")

    def add_file(
        self, local_path: str, name: Optional[str] = None, is_tmp: bool = False
    ) -> None:
        raise ValueError("Cannot add files to an artifact once it has been saved")

    def add_dir(self, path: str, name: Optional[str] = None) -> None:
        raise ValueError("Cannot add files to an artifact once it has been saved")

    def add_reference(
        self,
        uri: str,
        name: Optional[str] = None,
        checksum: bool = True,
        max_objects: Optional[int] = None,
    ):
        raise ValueError("Cannot add files to an artifact once it has been saved")

    def add(self, obj: WBValue, name: str) -> None:
        raise ValueError("Cannot add files to an artifact once it has been saved")

    def _add_download_root(self, dir_path: str) -> None:
        """Adds `dir_path` as one of the known directories which this
        artifact treated as a root"""
        self._download_roots.add(os.path.abspath(dir_path))

    def _is_download_root(self, dir_path: str) -> bool:
        """Determines if `dir_path` is a directory which this artifact as
        treated as a root for downloading"""
        return dir_path in self._download_roots

    def _local_path_to_name(self, file_path: str) -> Optional[str]:
        """Converts a local file path to a path entry in the artifact"""
        abs_file_path = os.path.abspath(file_path)
        abs_file_parts = abs_file_path.split(os.sep)
        for i in range(len(abs_file_parts) + 1):
            if self._is_download_root(os.path.join(os.sep, *abs_file_parts[:i])):
                return os.path.join(*abs_file_parts[i:])
        return None

    def _get_obj_entry(self, name: str) -> Tuple:
        """
        When objects are added with `.add(obj, name)`, the name is typically
        changed to include the suffix of the object type when serializing to JSON. So we need
        to be able to resolve a name, without tasking the user with appending .THING.json.
        This method returns an entry if it exists by a suffixed name.

        Args:
            name: (str) name used when adding
        """
        self._load_manifest()

        type_mapping = WBValue.type_mapping()
        for artifact_type_str in type_mapping:
            wb_class = type_mapping[artifact_type_str]
            wandb_file_name = wb_class.with_suffix(name)
            entry = self._manifest.entries.get(wandb_file_name)
            if entry is not None:
                return entry, wb_class
        return None, None

    def get_path(self, name: str) -> _DownloadedArtifactEntry:
        manifest = self._load_manifest()
        entry = manifest.entries.get(name)
        if entry is None:
            entry = self._get_obj_entry(name)[0]
            if entry is None:
                raise KeyError("Path not contained in artifact: %s" % name)
            else:
                name = entry.path

        return _DownloadedArtifactEntry(name, entry, self)

    def get(self, name: str) -> Optional[WBValue]:
        entry, wb_class = self._get_obj_entry(name)
        if entry is not None:
            # If the entry is a reference from another artifact, then get it directly from that artifact
            if self._manifest_entry_is_artifact_reference(entry):
                artifact = self._get_ref_artifact_from_entry(entry)
                return artifact.get(util.uri_from_path(entry.ref))

            # Special case for wandb.Table. This is intended to be a short term optimization.
            # Since tables are likely to download many other assets in artifact(s), we eagerly download
            # the artifact using the parallelized `artifact.download`. In the future, we should refactor
            # the deserialization pattern such that this special case is not needed.
            if wb_class == wandb.Table:
                self.download(recursive=True)

            # Get the ArtifactEntry
            item = self.get_path(entry.path)
            item_path = item.download()

            # Load the object from the JSON blob
            result = None
            json_obj = {}
            with open(item_path, "r") as file:
                json_obj = json.load(file)
            result = wb_class.from_json(json_obj, self)
            result._set_artifact_source(self, name)
            return result

    def download(self, root: Optional[str] = None, recursive: bool = False) -> str:
        dirpath = root or self._default_root()
        self._add_download_root(dirpath)
        manifest = self._load_manifest()
        nfiles = len(manifest.entries)
        size = sum(e.size for e in manifest.entries.values())
        log = False
        if nfiles > 5000 or size > 50 * 1024 * 1024:
            log = True
            termlog(
                "Downloading large artifact %s, %.2fMB. %s files... "
                % (self._artifact_name, size / (1024 * 1024), nfiles),
                newline=False,
            )
            start_time = datetime.datetime.now()

        # Force all the files to download into the same directory.
        # Download in parallel
        import multiprocessing.dummy  # this uses threads

        pool = multiprocessing.dummy.Pool(32)
        pool.map(partial(self._download_file, root=dirpath), manifest.entries)
        if recursive:
            pool.map(lambda artifact: artifact.download(), self._dependent_artifacts)
        pool.close()
        pool.join()

        self._is_downloaded = True

        if log:
            delta = relativedelta(datetime.datetime.now() - start_time)
            termlog(
                "Done. %s:%s:%s" % (delta.hours, delta.minutes, delta.seconds),
                prefix=False,
            )
        return dirpath

    def checkout(self, root: Optional[str] = None) -> str:
        dirpath = root or self._default_root(include_version=False)

        for root, _, files in os.walk(dirpath):
            for file in files:
                full_path = os.path.join(root, file)
                artifact_path = util.to_forward_slash_path(
                    os.path.relpath(full_path, start=dirpath)
                )
                try:
                    self.get_path(artifact_path)
                except KeyError:
                    # File is not part of the artifact, remove it.
                    os.remove(full_path)

        return self.download(root=dirpath)

    def verify(self, root: Optional[str] = None) -> None:
        dirpath = root or self._default_root()
        manifest = self._load_manifest()
        ref_count = 0

        for root, _, files in os.walk(dirpath):
            for file in files:
                full_path = os.path.join(root, file)
                artifact_path = util.to_forward_slash_path(
                    os.path.relpath(full_path, start=dirpath)
                )
                try:
                    self.get_path(artifact_path)
                except KeyError:
                    raise ValueError(
                        "Found file {} which is not a member of artifact {}".format(
                            full_path, self.name
                        )
                    )

        for entry in manifest.entries.values():
            if entry.ref is None:
                if (
                    artifacts.md5_file_b64(os.path.join(dirpath, entry.path))
                    != entry.digest
                ):
                    raise ValueError("Digest mismatch for file: %s" % entry.path)
            else:
                ref_count += 1
        if ref_count > 0:
            print("Warning: skipped verification of %s refs" % ref_count)

    def file(self, root: Optional[str] = None) -> str:
        """Download a single file artifact to dir specified by the <root>

        Arguments:
            root: (str, optional) The root directory in which to place the file. Defaults to './artifacts/<self.name>/'.

        Returns:
            (str): The full path of the downloaded file.
        """

        if root is None:
            root = os.path.join(".", "artifacts", self.name)

        manifest = self._load_manifest()
        nfiles = len(manifest.entries)
        if nfiles > 1:
            raise ValueError(
                "This artifact contains more than one file, call `.download()` to get all files or call "
                '.get_path("filename").download()'
            )

        return self._download_file(list(manifest.entries)[0], root=root)

    def _download_file(self, name: str, root: str) -> str:
        # download file into cache and copy to target dir
        return self.get_path(name).download(root)

    def _default_root(self, include_version: bool = True) -> str:
        root = (
            os.path.join(".", "artifacts", self.name)
            if include_version
            else os.path.join(".", "artifacts", self._sequence_name)
        )
        if platform.system() == "Windows":
            head, tail = os.path.splitdrive(root)
            root = head + tail.replace(":", "-")
        return root

    @normalize_exceptions
    def save(self) -> bool:
        """
        Persists artifact changes to the wandb backend.
        """
        mutation = gql(
            """
        mutation updateArtifact(
            $artifactID: ID!,
            $description: String,
            $metadata: JSONString,
            $aliases: [ArtifactAliasInput!]
        ) {
            updateArtifact(input: {
                artifactID: $artifactID,
                description: $description,
                metadata: $metadata,
                aliases: $aliases
            }) {
                artifact {
                    id
                }
            }
        }
        """
        )
        self.client.execute(
            mutation,
            variable_values={
                "artifactID": self.id,
                "description": self.description,
                "metadata": util.json_dumps_safer(self.metadata),
                "aliases": [
                    {"artifactCollectionName": self._sequence_name, "alias": alias,}
                    for alias in self._aliases
                ],
            },
        )
        return True

    def wait(self) -> "Artifact":
        return self

    # TODO: not yet public, but we probably want something like this.
    def _list(self) -> List[str]:
        manifest = self._load_manifest()
        return list(manifest.entries.keys())

    def __repr__(self) -> str:
        return "<Artifact {}>".format(self.id)

    def _load(self) -> Dict:
        query = gql(
            """
        query Artifact(
            $entityName: String!,
            $projectName: String!,
            $name: String!
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifact(name: $name) {
                    ...ArtifactFragment
                }
            }
        }
        %s
        """
            % ARTIFACT_FRAGMENT
        )
        response = None
        try:
            response = self.client.execute(
                query,
                variable_values={
                    "entityName": self.entity.name,
                    "projectName": self.project.name,
                    "name": self._artifact_name,
                },
            )
        except Exception:
            # we check for this after doing the call, since the backend supports raw digest lookups
            # which don't include ":" and are 32 characters long
            if ":" not in self._artifact_name and len(self._artifact_name) != 32:
                raise ValueError(
                    'Attempted to fetch artifact without alias (e.g. "<artifact_name>:v3" or "<artifact_name>:latest")'
                )
        if response is None or not response.get("project", {}).get("artifact", None):
            raise ValueError(
                'Project %s/%s does not contain artifact: "%s"'
                % (self.entity.name, self.project.name, self._artifact_name)
            )
        self._attrs = response["project"]["artifact"]
        return self._attrs

    # The only file should be wandb_manifest.json
    def _files(
        self, names: Optional[str] = None, per_page: int = 50
    ) -> "ArtifactFiles":
        return ArtifactFiles(self.client, self, names, per_page)

    def _load_manifest(self) -> artifacts.ArtifactManifest:
        if self._manifest is None:
            query = gql(
                """
            query ArtifactManifest(
                $entityName: String!,
                $projectName: String!,
                $name: String!
            ) {
                project(name: $projectName, entityName: $entityName) {
                    artifact(name: $name) {
                        currentManifest {
                            id
                            file {
                                id
                                directUrl
                            }
                        }
                    }
                }
            }
            """
            )
            response = self.client.execute(
                query,
                variable_values={
                    "entityName": self.entity.name,
                    "projectName": self.project.name,
                    "name": self._artifact_name,
                },
            )

            index_file_url = response["project"]["artifact"]["currentManifest"]["file"][
                "directUrl"
            ]
            with requests.get(index_file_url) as req:
                req.raise_for_status()
                self._manifest = artifacts.ArtifactManifest.from_manifest_json(
                    self, json.loads(six.ensure_text(req.content))
                )

            self._load_dependent_manifests()

        return self._manifest

    def _load_dependent_manifests(self) -> None:
        """Helper function to interrogate entries and ensure we have loaded their manifests"""
        # Make sure dependencies are avail
        for entry_key in self._manifest.entries:
            entry = self._manifest.entries[entry_key]
            if self._manifest_entry_is_artifact_reference(entry):
                dep_artifact = self._get_ref_artifact_from_entry(entry)
                dep_artifact._load_manifest()
                self._dependent_artifacts.append(dep_artifact)

    @staticmethod
    def _manifest_entry_is_artifact_reference(entry) -> bool:
        """Helper function determines if an ArtifactEntry in manifest is an artifact reference"""
        return (
            entry.ref is not None
            and urllib.parse.urlparse(entry.ref).scheme == "wandb-artifact"
        )

    def _get_ref_artifact_from_entry(
        self, entry: artifacts.ArtifactEntry
    ) -> "Artifact":
        """Helper function returns the referenced artifact from an entry"""
        artifact_id = util.host_from_path(entry.ref)
        return Artifact.from_id(util.hex_to_b64_id(artifact_id), self.client)

    def used_by(self) -> List[Run]:
        """Retrieves the runs which use this artifact directly

        Returns:
            [Run]: a list of Run objects which use this artifact
        """
        query = gql(
            """
            query Artifact(
                $id: ID!,
                $before: String,
                $after: String,
                $first: Int,
                $last: Int
            ) {
                artifact(id: $id) {
                    usedBy(before: $before, after: $after, first: $first, last: $last) {
                        edges {
                            node {
                                name
                                project {
                                    name
                                    entityName
                                }
                            }
                        }
                    }
                }
            }
        """
        )
        response = self.client.execute(query, variable_values={"id": self.id},)
        # yes, "name" is actually id
        runs = [
            Run(
                self.client,
                edge["node"]["project"]["entityName"],
                edge["node"]["project"]["name"],
                edge["node"]["name"],
            )
            for edge in response.get("artifact", {}).get("usedBy", {}).get("edges", [])
        ]
        return runs

    def logged_by(self) -> Optional[Run]:
        """Retrieves the run which logged this artifact

        Returns:
            Run: Run object which logged this artifact
        """
        query = gql(
            """
            query Artifact(
                $id: ID!
            ) {
                artifact(id: $id) {
                    createdBy {
                        ... on Run {
                            name
                            project {
                                name
                                entityName
                            }
                        }
                    }
                }
            }
        """
        )
        response = self.client.execute(query, variable_values={"id": self.id},)
        run_obj = response.get("artifact", {}).get("createdBy", {})
        if run_obj is not None:
            return Run(
                self.client,
                run_obj["project"]["entityName"],
                run_obj["project"]["name"],
                run_obj["name"],
            )

    def __setitem__(self, name: str, item: WBValue) -> None:
        return self.add(item, name)

    def __getitem__(self, name: str) -> Optional[WBValue]:
        return self.get(name)


class ArtifactVersions(Paginator):
    """An iterable collection of artifact versions associated with a project and optional filter.
    This is generally used indirectly via the `Api`.artifact_versions method
    """

    QUERY = gql(
        """
        query Artifacts($project: String!, $entity: String!, $type: String!, $collection: String!, $cursor: String, $perPage: Int = 50, $order: String, $filters: JSONString) {
            project(name: $project, entityName: $entity) {
                artifactType(name: $type) {
                    artifactSequence(name: $collection) {
                        name
                        artifacts(filters: $filters, after: $cursor, first: $perPage, order: $order) {
                            totalCount
                            edges {
                                node {
                                    ...ArtifactFragment
                                }
                                version
                                cursor
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
        %s
        """
        % ARTIFACT_FRAGMENT
    )

    def __init__(
        self,
        client: RetryingClient,
        project: Project,
        collection_name: str,
        type: str,
        filters: Optional[Dict] = None,
        order: Optional[str] = None,
        per_page: int = 50,
    ) -> None:
        self.entity = project.entity
        self.collection_name = collection_name
        self.type = type
        self.project = project
        filters = filters or {}
        self.filters = filters
        self.order = order
        variables = {
            "project": self.project.name,
            "entity": self.entity.name,
            "order": self.order,
            "type": self.type,
            "collection": self.collection_name,
            "filters": json.dumps(self.filters),
        }
        super(ArtifactVersions, self).__init__(client, variables, per_page)

    @property
    def length(self) -> Optional[int]:
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactSequence"][
                "artifacts"
            ]["totalCount"]
        else:
            return None

    @property
    def more(self) -> bool:
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactSequence"][
                "artifacts"
            ]["pageInfo"]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self) -> Optional[str]:
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifactSequence"][
                "artifacts"
            ]["edges"][-1]["cursor"]
        else:
            return None

    def convert_objects(self) -> List[Artifact]:
        if self.last_response["project"]["artifactType"]["artifactSequence"] is None:
            return []
        return [
            Artifact(
                self.client,
                self.entity,
                self.project,
                self.collection_name + ":" + a["version"],
                a["node"],
            )
            for a in self.last_response["project"]["artifactType"]["artifactSequence"][
                "artifacts"
            ]["edges"]
        ]


class ArtifactFiles(Paginator):
    QUERY = gql(
        """
        query ArtifactFiles(
            $entityName: String!,
            $projectName: String!,
            $artifactTypeName: String!,
            $artifactName: String!
            $fileNames: [String!],
            $fileCursor: String,
            $fileLimit: Int = 50
        ) {
            project(name: $projectName, entityName: $entityName) {
                artifactType(name: $artifactTypeName) {
                    artifact(name: $artifactName) {
                        ...ArtifactFilesFragment
                    }
                }
            }
        }
        %s
    """
        % ARTIFACT_FILES_FRAGMENT
    )

    def __init__(
        self,
        client: RetryingClient,
        artifact: Artifact,
        names: Optional[List[str]] = None,
        per_page: int = 50,
    ) -> None:
        self.artifact = artifact
        variables = {
            "entityName": artifact.entity,
            "projectName": artifact.project,
            "artifactTypeName": artifact.artifact_type_name,
            "artifactName": artifact.artifact_name,
            "fileNames": names,
        }
        super(ArtifactFiles, self).__init__(client, variables, per_page)

    @property
    def length(self) -> Optional[int]:
        # TODO
        return None

    @property
    def more(self) -> bool:
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifact"]["files"][
                "pageInfo"
            ]["hasNextPage"]
        else:
            return True

    @property
    def cursor(self) -> Optional[str]:
        if self.last_response:
            return self.last_response["project"]["artifactType"]["artifact"]["files"][
                "edges"
            ][-1]["cursor"]
        else:
            return None

    def update_variables(self) -> None:
        self.variables.update({"fileLimit": self.per_page, "fileCursor": self.cursor})

    def convert_objects(self) -> List[File]:
        return [
            File(self.client, r["node"])
            for r in self.last_response["project"]["artifactType"]["artifact"]["files"][
                "edges"
            ]
        ]

    def __repr__(self) -> str:
        return "<ArtifactFiles {} ({})>".format("/".join(self.artifact.path), len(self))


class BetaReport(Attrs):
    """BetaReport is a class associated with reports created in wandb.

    WARNING: this API will likely change in a future release

    Attributes:
        name (string): report name
        description (string): report descirpiton;
        user (User): the user that created the report
        spec (dict): the spec off the report;
        updated_at (string): timestamp of last update
    """

    def __init__(
        self, client: RetryingClient, attrs: Optional[Dict], project: Project
    ) -> None:
        self.client = client
        self.entity = project.entity
        self.project = project
        self.query_generator = QueryGenerator()
        super(BetaReport, self).__init__(dict(attrs))
        self._attrs["spec"] = json.loads(self._attrs["spec"])

    @property
    def sections(self) -> List["ReportSection"]:
        return [ReportSection(self, sec) for sec in self.spec["panelGroups"]]


class ReportSection(Attrs):
    def __init__(self, report: BetaReport, section: Dict) -> None:
        self.report = report
        super(ReportSection, self).__init__(section)

    def runs(self, per_page: int = 50, only_selected: bool = True) -> Runs:
        run_set_idx = self._attrs.get("openRunSet", 0)
        run_set = self._attrs["runSets"][run_set_idx]
        order = self.query_generator.key_to_server_path(run_set["sort"]["key"])
        if run_set["sort"].get("ascending"):
            order = "+" + order
        else:
            order = "-" + order
        filters = self.query_generator.filter_to_mongo(run_set["filters"])
        if only_selected:
            # TODO: handle this not always existing
            filters["$or"][0]["$and"].append(
                {"name": {"$in": run_set["selections"]["tree"]}}
            )
        return Runs(
            self.client,
            self.entity,
            self.project,
            filters=filters,
            order=order,
            per_page=per_page,
        )


class Reports(Paginator):
    """Reports is an iterable collection of `BetaReport` objects."""

    QUERY = gql(
        """
        query Run($project: String!, $entity: String!, $reportCursor: String,
            $reportLimit: Int = 50, $viewType: String = "runs", $viewName: String) {
            project(name: $project, entityName: $entity) {
                allViews(viewType: $viewType, viewName: $viewName, first:
                    $reportLimit, after: $reportCursor) {
                    edges {
                        node {
                            name
                            description
                            user {
                                username
                                photoUrl
                            }
                            spec
                            updatedAt
                        }
                        cursor
                    }
                }
            }
        }
        """
    )

    def __init__(
        self,
        client: RetryingClient,
        project: Project,
        names: Optional[List[str]] = None,
        per_page: int = 50,
    ) -> None:
        self.project = project
        self.entity = project.entity
        self.names = names
        variables = {
            "project": project.name,
            "entity": project.entity.name,
            "viewName": names,
        }
        super(Reports, self).__init__(client, variables, per_page)

    @property
    def length(self) -> int:
        # TODO: Add the count in backend
        return self.per_page

    @property
    def more(self) -> bool:
        if self.last_response:
            return (
                len(self.last_response["project"]["allViews"]["edges"]) == self.per_page
            )
        else:
            return True

    @property
    def cursor(self) -> Optional[str]:
        if self.last_response:
            return self.last_response["project"]["allViews"]["edges"][-1]["cursor"]
        else:
            return None

    def update_variables(self) -> None:
        self.variables.update(
            {"reportCursor": self.cursor, "reportLimit": self.per_page}
        )

    def convert_objects(self) -> List[BetaReport]:
        return [
            BetaReport(self.client, r["node"], project=self.project)
            for r in self.last_response["project"]["allViews"]["edges"]
        ]

    def __repr__(self) -> str:
        return "<Reports {}>".format("/".join(self.project.path))


class Sweeps(object):
    def __init__(self, client: RetryingClient, project: Project) -> None:
        self.client = client
        self.entity = project.entity
        self.project = project

    def __getitem__(self, sweep_id: str) -> Sweep:
        return Sweep(client=self.client, project=self.project, sweep_id=sweep_id)


class HistoryScan(object):
    QUERY = gql(
        """
        query HistoryPage($entity: String!, $project: String!, $run: String!, $minStep: Int64!, $maxStep: Int64!, $pageSize: Int!) {
            project(name: $project, entityName: $entity) {
                run(name: $run) {
                    history(minStep: $minStep, maxStep: $maxStep, samples: $pageSize)
                }
            }
        }
        """
    )

    def __init__(
        self,
        client: RetryingClient,
        run: Run,
        min_step: int,
        max_step: int,
        page_size: int = 1000,
    ) -> None:
        self.client = client
        self.run = run
        self.page_size = page_size
        self.min_step = min_step
        self.max_step = max_step
        self.page_offset = min_step  # minStep for next page
        self.scan_offset = 0  # index within current page of rows
        self.rows = []  # current page of rows

    def __iter__(self) -> "HistoryScan":
        self.page_offset = self.min_step
        self.scan_offset = 0
        self.rows = []
        return self

    def __next__(self) -> Dict:
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset >= self.max_step:
                raise StopIteration()
            self._load_next()

    next = __next__

    @normalize_exceptions
    @retry.retriable(
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException),
    )
    def _load_next(self) -> None:
        max_step = self.page_offset + self.page_size
        if max_step > self.max_step:
            max_step = self.max_step
        variables = {
            "entity": self.run.entity,
            "project": self.run.project,
            "run": self.run.id,
            "minStep": int(self.page_offset),
            "maxStep": int(max_step),
            "pageSize": int(self.page_size),
        }

        res = self.client.execute(self.QUERY, variable_values=variables)
        res = res["project"]["run"]["history"]
        self.rows = [json.loads(row) for row in res]
        self.page_offset += self.page_size
        self.scan_offset = 0


class SampledHistoryScan(object):
    QUERY = gql(
        """
        query SampledHistoryPage($entity: String!, $project: String!, $run: String!, $spec: JSONString!) {
            project(name: $project, entityName: $entity) {
                run(name: $run) {
                    sampledHistory(specs: [$spec])
                }
            }
        }
        """
    )

    def __init__(
        self,
        client: RetryingClient,
        run: Run,
        keys: List[str],
        min_step: int,
        max_step: int,
        page_size: int = 1000,
    ) -> None:
        self.client = client
        self.run = run
        self.keys = keys
        self.page_size = page_size
        self.min_step = min_step
        self.max_step = max_step
        self.page_offset = min_step  # minStep for next page
        self.scan_offset = 0  # index within current page of rows
        self.rows = []  # current page of rows

    def __iter__(self) -> "SampledHistoryScan":
        self.page_offset = self.min_step
        self.scan_offset = 0
        self.rows = []
        return self

    def __next__(self) -> Dict:
        while True:
            if self.scan_offset < len(self.rows):
                row = self.rows[self.scan_offset]
                self.scan_offset += 1
                return row
            if self.page_offset >= self.max_step:
                raise StopIteration()
            self._load_next()

    next = __next__

    @normalize_exceptions
    @retry.retriable(
        check_retry_fn=util.no_retry_auth,
        retryable_exceptions=(RetryError, requests.RequestException),
    )
    def _load_next(self) -> None:
        max_step = self.page_offset + self.page_size
        if max_step > self.max_step:
            max_step = self.max_step
        variables = {
            "entity": self.run.entity,
            "project": self.run.project,
            "run": self.run.id,
            "spec": json.dumps(
                {
                    "keys": self.keys,
                    "minStep": int(self.page_offset),
                    "maxStep": int(max_step),
                    "samples": int(self.page_size),
                }
            ),
        }

        res = self.client.execute(self.QUERY, variable_values=variables)
        res = res["project"]["run"]["sampledHistory"]
        self.rows = res[0]
        self.page_offset += self.page_size
        self.scan_offset = 0


# ==filter parsing== #


def _convert_compare(op: Any, left: Any, right: Any) -> dict:
    opname = {
        ast.Lt: "$lt",
        ast.Gt: "$Gt",
        ast.LtE: "$lte",
        ast.GtE: "$gte",
        ast.Eq: "$eq",
        ast.NotEq: "$ne",
        ast.Is: "$eq",
        ast.IsNot: "$ne",
        ast.In: "$in",
        ast.NotIn: "$nin",
    }.get(op.__class__)
    if not opname:
        raise Exception("Unsupported compare op: " + op.__class__.__name__)
    return {opname: [_traverse(left), _traverse(right)]}


def _to_binary_compare(expr: ast.Compare) -> Dict:
    outs = []
    left = expr.left
    for i in range(len(expr.ops)):
        right = expr.comparators[i]
        outs.append(_convert_compare(expr.ops[i], left, right))
        left = right
    if len(outs) == 1:
        return outs[0]
    return {"$and": outs}


def _traverse(expr: Any) -> Any:
    if isinstance(expr, ast.Expr):
        expr = expr.value
    if isinstance(expr, ast.BoolOp):
        op = expr.op
        if not isinstance(op, (ast.And, ast.Or)):
            raise Exception("Unsupported binary op: " + op.__name__)
        return {
            "$%s" % op.__class__.__name__.lower(): list(map(_traverse, expr.values))
        }
    elif isinstance(expr, ast.UnaryOp):
        op = expr.op
        if not isinstance(op, ast.Not):
            raise Exception("Unsupported unary op: " + op.__name__)
        return {"$not": _traverse(expr.operand)}
    elif isinstance(expr, ast.Name):
        return expr.id
    elif isinstance(expr, ast.Num):
        return expr.n
    elif isinstance(expr, ast.Compare):
        return _to_binary_compare(expr)
    elif isinstance(expr, ast.Attribute):
        return _traverse(expr.value) + expr.attr
    else:
        raise Exception("Unsupported operation: %s" % expr)


def parse_filter(f: str) -> dict:
    tree = ast.parse(f)
    if len(tree.body) == 0:
        raise Exception("Empty filter string.")
    elif len(tree.body) > 1:
        raise Exception("Invalid filter string: %s" % f)
    if not isinstance(tree.body[0], ast.Expr):
        raise Exception("Expected expression, received %s" & type(tree.body[0]))
    expr = tree.body[0]
    ret = _traverse(expr)
    return ret


# ==/filter parsing== #
