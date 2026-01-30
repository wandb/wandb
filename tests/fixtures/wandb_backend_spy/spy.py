from __future__ import annotations

import contextlib
import dataclasses
import json
import threading
from typing import Any, Iterator

import fastapi
from typing_extensions import NamedTuple

from . import gql_match


class WandbBackendSpy:
    """A spy that intercepts interactions with the W&B backend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: _Runs = _Runs()
        self._gql_stubs: list[gql_match.GQLStub] = []
        self._filestream_stubs: list[_FileStreamResponse] = []

    @contextlib.contextmanager
    def freeze(self) -> Iterator[WandbBackendSnapshot]:
        """A context manager in which the spied state can be queried.

        Usage:

            with wandb_backend_spy.freeze() as snapshot:
                history = snapshot.history(run_id=run_id)
                assert history[0]["metric"] == "expected_value"
        """
        snapshot = WandbBackendSnapshot()

        with self._lock:
            snapshot._spy = self
            try:
                yield snapshot
            finally:
                snapshot._spy = None

    # Provide an alias so that tests don't need to import gql_match.py.
    gql = gql_match

    def stub_gql(
        self,
        match: gql_match.Matcher,
        respond: gql_match.Responder,
    ) -> None:
        """Stub the GraphQL endpoint.

        Later calls to `stub_gql` take precedence. For example, this
        responds "b" to the first UpsertBucket call, then "a" to all others:

            gql = wandb_backend_spy.gql
            matcher = gql.Matcher(operation="UpsertBucket")
            wandb_backend_spy.stub_gql(matcher, gql.Constant(content="a"))
            wandb_backend_spy.stub_gql(matcher, gql.once(content="b"))

        This allows helper fixtures to set defaults for tests.

        Args:
            match: Which GraphQL requests to intercept.
            respond: How to handle matched requests.
        """
        with self._lock:
            self._gql_stubs.append((match, respond))

    def stub_filestream(
        self,
        body: str | dict[str, Any],
        *,
        status: int,
        n_times: int = 1,
    ) -> None:
        """Stub the FileStream endpoint.

        The next `n_times` requests to FileStream are intercepted and return
        the given status and body. Unlike `stub_gql`, this does not allow
        selecting specific requests to intercept.

        Later calls to `stub_filestream` take precedence.

        Args:
            body: The request body. If a dict, it is converted to JSON.
            status: The HTTP status code to return.
            n_times: The number of requests to intercept.
        """
        if not isinstance(body, str):
            body = json.dumps(body)

        with self._lock:
            self._filestream_stubs.extend(
                [_FileStreamResponse(status=status, body=body)] * n_times
            )

    def intercept_graphql(self, request_raw: bytes) -> fastapi.Response | None:
        """Intercept a GraphQL request to produce a fake response."""
        with self._lock:
            stubs = self._gql_stubs
        if not stubs:
            return None

        request = json.loads(request_raw)
        query = request.get("query", "")
        variables = request.get("variables", {})

        for matcher, responder in reversed(stubs):
            if not matcher.matches(query, variables):
                continue

            response = responder.respond(query, variables)
            if not response:
                continue

            return response

        return None

    def intercept_filestream(self) -> fastapi.Response | None:
        """Intercept a FileStream request to produce a fake response."""
        with self._lock:
            stubs = self._filestream_stubs
            if not stubs:
                return None
            stub = stubs.pop()

        return fastapi.Response(
            status_code=stub.status,
            content=stub.body,
        )

    def post_graphql(
        self,
        request_raw: bytes,
        response_raw: bytes,
        response_code: int,
    ) -> None:
        """Spy on a GraphQL request and response."""
        request: dict[str, Any] = json.loads(request_raw)

        with self._lock:
            query: str | None = request.get("query")
            variables: dict[str, Any] | None = request.get("variables")
            if query is None or variables is None:
                return

            if 200 <= response_code < 300:
                response: dict[str, Any] = json.loads(response_raw)
                self._spy_upsert_bucket(query, variables, response)

    def _spy_upsert_bucket(
        self,
        query: str,
        variables: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        """Change spied state based on successful UpsertBucket requests.

        Requires self._lock.
        """
        # NOTE: This is an exact-string match to the query we send.
        # It does not depend on the GraphQL schema.
        if "mutation UpsertBucket" not in query:
            return

        # "name" is the usual run ID (part of the run URL),
        # and "id" is the "storage ID" which is sometimes used in
        # the public API. We use both interchangeably in tests to keep
        # usage simple.
        if "name" in variables:
            run_id = variables["name"]
        elif "id" in variables:
            run_id = variables["id"]
        else:
            raise KeyError("Unexpected UpsertBucket without name or id")

        # All variants of the UpsertBucket mutation request the entity and
        # project name. This is lucky as it lets us identify the run based
        # on the server's response here.
        #
        # In case the response has an unexpected structure, these default names
        # may help debug tests. We would need a more complicated setup to
        # correctly record such mutations.
        entity = "wandb_backend_spy-ERROR"
        project = "wandb_backend_spy-ERROR"
        with contextlib.suppress(KeyError):
            bucket = response["data"]["upsertBucket"]["bucket"]
            project = bucket["project"]["name"]
            entity = bucket["project"]["entity"]["name"]

        run = self._runs.setdefault(entity, project, run_id, _RunData())

        config = variables.get("config")
        if config is not None:
            run._config_json_string = config

        job_type = variables.get("jobType")
        if job_type is not None:
            run._job_type = job_type

        tags = variables.get("tags")
        if tags is not None:
            run._tags = tags

        repo = variables.get("repo")
        if repo is not None:
            run._remote = repo

        commit = variables.get("commit")
        if commit is not None:
            run._commit = commit

        sweep = variables.get("sweep")
        if sweep is not None:
            run._sweep_name = sweep

        summary_metrics = variables.get("summaryMetrics")
        if summary_metrics is not None:
            # We use the wandb-summary.json file of the FileStream API
            # as the source of truth for the run's summary.
            summary = run._file_stream_files.setdefault("wandb-summary.json", {})
            last_line_offset = max(summary.keys(), default=0)
            summary[last_line_offset] = summary_metrics

    def post_file_stream(
        self,
        request_raw: bytes,
        response_raw: bytes,
        *,
        entity: str,
        project: str,
        run_id: str,
    ) -> None:
        """Spy on a FileStream request and response."""
        request = json.loads(request_raw)

        with self._lock:
            run = self._runs.setdefault(entity, project, run_id, _RunData())

            run._was_ever_preempting |= request.get("preempting", False)
            run._preempting = request.get("preempting", False)
            run._uploaded_files |= set(request.get("uploaded", []))
            run._completed = request.get("complete", False)
            run._exit_code = request.get("exitcode")

            for file_name, file_data in request.get("files", {}).items():
                file = run._file_stream_files.setdefault(file_name, {})

                offset = file_data["offset"]
                for line in file_data["content"]:
                    file[offset] = line
                    offset += 1


class WandbBackendSnapshot:
    """A snapshot of the W&B backend state."""

    _spy: WandbBackendSpy | None

    def run_ids(self) -> set[str]:
        """Returns the IDs of all runs."""
        spy = self._assert_valid()
        return spy._runs.all_ids()

    def uploaded_files(self, *, run_id: str) -> set[str]:
        """Returns the set of files uploaded for the run.

        This is based on the values reported in the "uploaded" field of
        FileStream requests, and doesn't track actual file uploads.
        """
        spy = self._assert_valid()
        return spy._runs.get(run_id)._uploaded_files

    def history(
        self,
        *,
        run_id: str,
        entity: str | None = None,
        project: str | None = None,
    ) -> dict[int, Any]:
        """Returns the history file for the run.

        The file is represented as a dict that maps integer offsets to
        JSON objects.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()
        run = spy._runs.get(run_id, entity=entity, project=project)

        history_file = run._file_stream_files.get("wandb-history.jsonl", {})
        history_parsed: dict[int, Any] = {}
        for offset, line in history_file.items():
            history_parsed[offset] = json.loads(line)
        return history_parsed

    def output(self, *, run_id: str) -> dict[int, str]:
        """Returns the run's console logs uploaded via FileStream.

        The file is represented as a dict that maps integer offsets to
        the printed output string.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()
        run = spy._runs.get(run_id)

        return dict(run._file_stream_files.get("output.log", {}))

    def summary(self, *, run_id: str) -> Any:
        """Returns the summary for the run as a JSON object.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()
        run = spy._runs.get(run_id)

        summary_file = run._file_stream_files.get("wandb-summary.json", {})
        last_line_offset = max(summary_file.keys(), default=None)
        if last_line_offset is None:
            return {}
        return json.loads(summary_file[last_line_offset])

    def system_metrics(self, *, run_id: str) -> dict[int, Any]:
        """Returns the system metrics file for the run.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()
        run = spy._runs.get(run_id)

        events_file = run._file_stream_files.get("wandb-events.jsonl", {})
        events_parsed: dict[int, Any] = {}
        for offset, line in events_file.items():
            events_parsed[offset] = json.loads(line)
        return events_parsed

    def config(self, *, run_id: str) -> dict[str, Any]:
        """Returns the config for the run as a JSON object.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
            AssertionError: if no config was uploaded for the run.
        """
        spy = self._assert_valid()

        config = spy._runs.get(run_id)._config_json_string
        if config is None:
            raise AssertionError(f"No config for run {run_id}")

        return json.loads(config)

    def telemetry(self, *, run_id: str) -> dict[str, Any]:
        """Returns the telemetry for the run as a JSON object.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
            AssertionError: if no telemetry was uploaded for the run.
        """
        config = self.config(run_id=run_id)

        try:
            return config["_wandb"]["value"]["t"]
        except KeyError as e:
            raise AssertionError(f"No telemetry for run {run_id}") from e

    def metrics(self, *, run_id: str) -> dict[str, Any]:
        """Returns the metrics for the run as a JSON object.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
            AssertionError: if no metrics were uploaded for the run.
        """
        config = self.config(run_id=run_id)

        try:
            return config["_wandb"]["value"]["m"]
        except KeyError as e:
            raise AssertionError(f"No metrics for run {run_id}") from e

    def job_type(self, *, run_id: str) -> list[str]:
        """Returns the run's job type.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()
        return spy._runs.get(run_id)._job_type

    def tags(self, *, run_id: str) -> list[str]:
        """Returns the run's tags.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()
        return spy._runs.get(run_id)._tags

    def remote(self, *, run_id: str) -> str | None:
        """Returns the run's remote repository, if any.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()
        return spy._runs.get(run_id)._remote

    def commit(self, *, run_id: str) -> str | None:
        """Returns the run's commit, if any.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()
        return spy._runs.get(run_id)._commit

    def sweep_name(self, *, run_id: str) -> str | None:
        """Returns the sweep to which the run belongs, if any.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()
        return spy._runs.get(run_id)._sweep_name

    def preempting(self, *, run_id: str) -> bool:
        """Returns the latest preempting value for the run."""
        spy = self._assert_valid()
        return spy._runs.get(run_id)._preempting

    def was_ever_preempting(self, *, run_id: str) -> bool:
        """Returns whether the run was ever marked 'preempting'."""
        spy = self._assert_valid()
        return spy._runs.get(run_id)._was_ever_preempting

    def completed(self, *, run_id: str) -> bool:
        """Returns whether the run was marked as completed."""
        spy = self._assert_valid()
        return spy._runs.get(run_id)._completed

    def exit_code(self, *, run_id: str) -> int | None:
        """Returns the exit code of the run."""
        spy = self._assert_valid()
        return spy._runs.get(run_id)._exit_code

    def _assert_valid(self) -> WandbBackendSpy:
        """Raise an error if we're not inside freeze()."""
        if not self._spy:
            raise AssertionError("Snapshot cannot be used outside of freeze().")

        return self._spy


class _EntityProject(NamedTuple):
    """A run's entity and project."""

    entity: str
    project: str


class _Runs:
    """A mapping from run paths to recorded run data."""

    def __init__(self) -> None:
        self._run_by_id: dict[str, dict[_EntityProject, _RunData]] = {}

    def all_ids(self) -> set[str]:
        """Returns all run IDs recorded."""
        return set(self._run_by_id.keys())

    def setdefault(
        self,
        entity: str,
        project: str,
        run_id: str,
        value: _RunData,
    ) -> _RunData:
        """Returns the data for the specified run, maybe creating it."""
        entity_project_to_run = self._run_by_id.setdefault(run_id, {})
        return entity_project_to_run.setdefault(
            _EntityProject(entity, project),
            value,
        )

    def get(
        self,
        run_id: str,
        *,
        entity: str | None = None,
        project: str | None = None,
    ) -> _RunData:
        """Returns the data for the specified run.

        Args:
            run_id: The run's ID.
            entity: The run's entity, or None if unambiguous.
            project: The run's project, or None if unambiguous.

        Raises:
            KeyError: If the specified run is not found.
        """
        entity_project_to_run = self._run_by_id.get(run_id)
        if not entity_project_to_run:
            raise KeyError(f"No run with ID {run_id}")

        matches: dict[_EntityProject, _RunData] = {}
        for (e, p), data in entity_project_to_run.items():
            if entity is not None and e and e != entity:
                continue
            if project is not None and p and p != project:
                continue
            matches[_EntityProject(e, p)] = data

        if not matches:
            raise KeyError(f"No run matching {run_id=}, {entity=}, {project=}")

        if len(matches) > 1:
            message = (
                "Found more than one entry matching"
                + f" {run_id=}, {entity=}, {project=}:"
                + f" {list(matches.keys())}"
            )
            raise KeyError(message)

        return list(matches.values())[0]


class _RunData:
    def __init__(self) -> None:
        # See docs on WandbBackendSnapshot methods.
        self._preempting = False
        self._was_ever_preempting = False
        self._uploaded_files: set[str] = set()
        self._file_stream_files: dict[str, dict[int, str]] = {}
        self._config_json_string: str | None = None
        self._job_type: str | None = None
        self._tags: list[str] = []
        self._remote: str | None = None
        self._commit: str | None = None
        self._sweep_name: str | None = None
        self._completed = False
        self._exit_code: int | None = None


@dataclasses.dataclass(frozen=True)
class _FileStreamResponse:
    """A response to a FileStream request."""

    status: int
    body: str
