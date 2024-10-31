from __future__ import annotations

import contextlib
import json
import threading
from typing import Any, Iterator

import fastapi


class WandbBackendSpy:
    """A spy that intercepts interactions with the W&B backend."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, _RunData] = {}

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

    def post_graphql(self, contents: bytes) -> fastapi.Response | None:
        """Intercept a GraphQL request."""
        return None

    def post_file_stream(
        self,
        contents: bytes,
        *,
        entity: str,
        project: str,
        run_id: str,
    ) -> fastapi.Response | None:
        """Intercept a FileStream request."""
        with self._lock:
            run = self._runs.setdefault(run_id, _RunData())

            request = json.loads(contents)

            for file_name, file_data in request.get("files", {}).items():
                file = run._file_stream_files.setdefault(file_name, {})

                offset = file_data["offset"]
                for line in file_data["content"]:
                    file[offset] = line
                    offset += 1

        return None


class WandbBackendSnapshot:
    """A snapshot of the W&B backend state."""

    _spy: WandbBackendSpy | None

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

    def _assert_valid(self) -> WandbBackendSpy:
        """Raise an error if we're not inside freeze()."""
        if not self._spy:
            raise AssertionError("Snapshot cannot be used outside of freeze().")

        return self._spy


class _RunData:
    def __init__(self) -> None:
        self._file_stream_files: dict[str, dict[int, Any]] = {}
