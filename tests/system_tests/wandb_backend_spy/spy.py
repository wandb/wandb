from __future__ import annotations

import contextlib
import json
import threading
from typing import Any, Iterator

import fastapi

from . import gql_match


class WandbBackendSpy:
    """A spy that intercepts interactions with the W&B backend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, _RunData] = {}
        self._gql_stubs: list[gql_match.GQLStub] = []

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

    def intercept_graphql(self, request_raw: bytes) -> fastapi.Response | None:
        """Intercept a GraphQL request to produce a fake response."""
        with self._lock:
            if not self._gql_stubs:
                return None

            request = json.loads(request_raw)
            query = request.get("query", "")
            variables = request.get("variables", {})

            for matcher, responder in reversed(self._gql_stubs):
                if not matcher.matches(query, variables):
                    continue

                response = responder.respond(query, variables)
                if not response:
                    continue

                return response

            return None

    def post_graphql(
        self,
        request_raw: bytes,
        response_raw: bytes,
    ) -> None:
        """Spy on a GraphQL request and response."""
        request = json.loads(request_raw)

        with self._lock:
            query: str | None = request.get("query")
            variables: dict[str, Any] | None = request.get("variables")
            if query is None or variables is None:
                return

            self._spy_run_config(query, variables)

    def _spy_run_config(self, query: str, variables: dict[str, Any]) -> None:
        """Detect changes to run config.

        Requires self._lock.
        """
        # NOTE: This is an exact-string match to the query we send.
        # It does not depend on the GraphQL schema.
        if "mutation UpsertBucket" not in query:
            return

        if "config" not in variables:
            return

        run_id = variables["name"]
        config = variables["config"]

        run = self._runs.setdefault(run_id, _RunData())
        run._config_json_string = config

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
            run = self._runs.setdefault(run_id, _RunData())

            run._was_ever_preempting |= request.get("preempting", False)
            run._uploaded_files |= set(request.get("uploaded", []))

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
        return set(spy._runs.keys())

    def uploaded_files(self, *, run_id: str) -> set[str]:
        """Returns the set of files uploaded for the run.

        This is based on the values reported in the "uploaded" field of
        FileStream requests, and doesn't track actual file uploads.
        """
        spy = self._assert_valid()
        return spy._runs[run_id]._uploaded_files

    def history(self, *, run_id: str) -> dict[int, Any]:
        """Returns the history file for the run.

        The file is represented as a dict that maps integer offsets to
        JSON objects.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()

        try:
            run = spy._runs[run_id]
        except KeyError as e:
            raise KeyError(f"No run with ID {run_id}") from e

        history_file = run._file_stream_files.get("wandb-history.jsonl", {})
        history_parsed: dict[int, Any] = {}
        for offset, line in history_file.items():
            history_parsed[offset] = json.loads(line)
        return history_parsed

    def summary(self, *, run_id: str) -> Any:
        """Returns the summary for the run as a JSON object.

        Args:
            run_id: The ID of the run.

        Raises:
            KeyError: if the run does not exist.
        """
        spy = self._assert_valid()

        try:
            run = spy._runs[run_id]
        except KeyError as e:
            raise KeyError(f"No run with ID {run_id}") from e

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

        try:
            run = spy._runs[run_id]
        except KeyError as e:
            raise KeyError(f"No run with ID {run_id}") from e

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

        try:
            config = spy._runs[run_id]._config_json_string
        except KeyError as e:
            raise KeyError(f"No run with ID {run_id}") from e

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

    def was_ever_preempting(self, *, run_id: str) -> bool:
        """Returns whether the run was ever marked 'preempting'."""
        spy = self._assert_valid()
        return spy._runs[run_id]._was_ever_preempting

    def _assert_valid(self) -> WandbBackendSpy:
        """Raise an error if we're not inside freeze()."""
        if not self._spy:
            raise AssertionError("Snapshot cannot be used outside of freeze().")

        return self._spy


class _RunData:
    def __init__(self) -> None:
        self._was_ever_preempting = False
        self._uploaded_files: set[str] = set()
        self._file_stream_files: dict[str, dict[int, Any]] = {}
        self._config_json_string: str | None = None
