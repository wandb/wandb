"""W&B Public API for Hugging Face registry imports.

The server performs the import; the client only starts it and polls its state.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from typing_extensions import Self, override

from wandb.apis.normalize import normalize_exceptions
from wandb.apis.paginator import RelayPaginator
from wandb.errors import Error
from wandb.errors.term import termlog
from wandb.sdk.artifacts.exceptions import WaitTimeoutError

if TYPE_CHECKING:
    from wandb._pydantic import Connection
    from wandb.apis.public.service_api import ServiceApi
    from wandb.sdk.artifacts._generated import RegistryHuggingFaceImportFragment
    from wandb.sdk.artifacts.artifact import Artifact

HuggingFaceSourceStatus = Literal[
    "OK",
    "EMPTY",
    "GATED",
    "GATED_TERMS_NOT_ACCEPTED",
    "NOT_FOUND",
    "REVISION_NOT_FOUND",
    "TOKEN_INVALID",
    "TOO_LARGE",
    "UNKNOWN",
]
"""The possible statuses of a Hugging Face source check."""

HuggingFaceImportState = Literal[
    "CREATED",
    "STARTING",
    "RUNNING",
    "STOPPING",
    "SUCCEEDED",
    "FAILED",
    "STOPPED",
]
"""The possible states of a Hugging Face import."""

_TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "STOPPED"})
"""Import states after which no more progress is expected."""


@dataclass(frozen=True)
class HuggingFaceSourceFile:
    """A single file in a Hugging Face repository."""

    path: str
    """The path of the file in the repository."""

    size_bytes: int | None
    """The size of the file in bytes, if known."""


@dataclass(frozen=True)
class HuggingFaceSource:
    """The result of checking a Hugging Face repository as an import source.

    Returned by `Api.check_huggingface_source()`.
    """

    repo_id: str
    """The Hugging Face repo id that was checked, e.g. `org/name`."""

    revision: str | None
    """The requested revision (branch, tag or commit), if any."""

    status: HuggingFaceSourceStatus
    """The outcome of the check."""

    message: str | None
    """A human-readable detail about the status, if the server returned one."""

    resolved_revision: str | None
    """The commit the requested revision resolved to, if it resolved."""

    size_bytes: int | None
    """The total size of the files that would be imported, if known."""

    files: tuple[HuggingFaceSourceFile, ...]
    """The files that would be imported."""

    @property
    def ok(self) -> bool:
        """Whether the source can be imported as-is."""
        return self.status == "OK"


@dataclass(frozen=True)
class HuggingFaceImportEvent:
    """An event in the history of a Hugging Face import."""

    id: str
    """The unique ID of the event."""

    time: str
    """When the event occurred."""

    name: str
    """The name of the event."""

    message: str | None
    """A human-readable detail, if the server recorded one."""


class HuggingFaceImportError(Error):
    """A Hugging Face import finished unsuccessfully.

    Raised by `HuggingFaceImport.wait()` when the import fails or is stopped.
    """

    def __init__(
        self,
        import_id: str,
        state: str,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        self.import_id = import_id
        """The ID of the import that did not succeed."""

        self.state = state
        """The terminal state of the import (`FAILED` or `STOPPED`)."""

        self.error_code = error_code
        """The error code recorded by the server, if any."""

        self.error_message = error_message
        """The error message recorded by the server, if any."""

        detail = error_message or error_code or "no error details"
        super().__init__(f"Hugging Face import {import_id!r} {state.lower()}: {detail}")


class HuggingFaceImport:
    """A handle to a server-side Hugging Face import.

    Returned by `Registry.import_from_huggingface()` and
    `Api.huggingface_import()`. The import runs on the server; this object
    only reports and polls its state.
    """

    def __init__(
        self,
        service_api: ServiceApi,
        attrs: RegistryHuggingFaceImportFragment,
    ):
        self._service_api = service_api
        self._current = attrs

    @property
    def id(self) -> str:
        """The unique ID of the import."""
        return self._current.id

    @property
    def state(self) -> HuggingFaceImportState:
        """The current state of the import."""
        return self._current.state.value  # type: ignore[return-value]

    @property
    def phase(self) -> str | None:
        """The worker phase while the import is running."""
        return self._current.phase

    @property
    def error_code(self) -> str | None:
        """The error code recorded on a failed import, if any."""
        return self._current.error_code

    @property
    def error_message(self) -> str | None:
        """The error message recorded on a failed import, if any."""
        return self._current.error_message

    @property
    def stats(self) -> dict[str, Any] | None:
        """Import statistics reported by the worker, if any."""
        if (stats := self._current.stats) is None:
            return None
        return json.loads(stats)

    @property
    def created_at(self) -> str:
        """When the import was created."""
        return self._current.created_at

    @property
    def terminal_at(self) -> str | None:
        """When the import reached a terminal state, if it has."""
        return self._current.terminal_at

    @property
    def repo_id(self) -> str:
        """The Hugging Face repo id being imported, e.g. `org/name`."""
        return self._current.hf_repo_id

    @property
    def requested_revision(self) -> str:
        """The revision the import was requested with."""
        return self._current.hf_requested_revision

    @property
    def resolved_revision(self) -> str | None:
        """The commit the requested revision resolved to, if resolved."""
        return self._current.hf_resolved_revision

    @property
    def entity(self) -> str | None:
        """The entity whose project receives the imported artifact."""
        if entity := self._current.entity:
            return entity.name
        return None

    @property
    def project(self) -> str | None:
        """The project that receives the imported artifact."""
        if project := self._current.project:
            return project.name
        return None

    @property
    def registry(self) -> str | None:
        """The name of the destination registry, without the `wandb-registry-`
        prefix."""
        from wandb.sdk.artifacts._validators import remove_registry_prefix

        if project := self._current.registry_project:
            return remove_registry_prefix(project.name)
        return None

    @property
    def collection(self) -> str | None:
        """The name of the destination registry collection."""
        return self._current.registry_collection_name

    @property
    def artifact_ref(self) -> str | None:
        """The `entity/project/name:alias` ref of the imported artifact.

        `None` until the import produces one."""
        return self._current.artifact_ref

    @property
    def registry_ref(self) -> str | None:
        """The `entity/project/name:alias` ref of the linked registry version.

        `None` until the import produces one."""
        return self._current.registry_ref

    @property
    def events(self) -> list[HuggingFaceImportEvent]:
        """The events recorded for the import, oldest first."""
        return [
            HuggingFaceImportEvent(
                id=edge.node.id,
                time=edge.node.time,
                name=edge.node.name,
                message=edge.node.message,
            )
            for edge in self._current.events.edges
        ]

    @property
    def done(self) -> bool:
        """Whether the import reached a terminal state."""
        return self.state in _TERMINAL_STATES

    @normalize_exceptions
    def refresh(self) -> Self:
        """Re-fetch the import's state from the server.

        Returns:
            This `HuggingFaceImport`, updated in place.

        Raises:
            CommError: If the import no longer exists or the request fails.
        """
        from wandb.sdk.artifacts._generated import REGISTRY_HUGGING_FACE_IMPORT_GQL
        from wandb.sdk.artifacts._generated import (
            RegistryHuggingFaceImport as _RegistryHuggingFaceImport,
        )

        result = self._service_api.execute_graphql(
            REGISTRY_HUGGING_FACE_IMPORT_GQL,
            variables={"id": self.id},
            parse=_RegistryHuggingFaceImport.model_validate_json,
        )
        if (fragment := result.registry_hugging_face_import) is None:
            raise ValueError(f"Hugging Face import {self.id!r} was not found.")
        self._current = fragment
        return self

    def wait(self, timeout: float | None = None, *, poll_interval: float = 5.0) -> Self:
        """Poll the server until the import reaches a terminal state.

        Args:
            timeout: Maximum number of seconds to wait. `None` waits
                indefinitely.
            poll_interval: Seconds between state polls.

        Returns:
            This `HuggingFaceImport` once it has `SUCCEEDED`.

        Raises:
            WaitTimeoutError: If `timeout` elapsed first.
            HuggingFaceImportError: If the import `FAILED` or was `STOPPED`.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        logged_phase: str | None = None
        seen_event_ids: set[str] = set()
        try:
            while True:
                if self.phase != logged_phase:
                    logged_phase = self.phase
                    if logged_phase is not None:
                        termlog(f"Hugging Face import {self.id}: {logged_phase}")
                for event in self.events:
                    if event.id not in seen_event_ids:
                        seen_event_ids.add(event.id)
                        detail = f": {event.message}" if event.message else ""
                        termlog(f"Hugging Face import {self.id}: {event.name}{detail}")

                if self.done:
                    break

                if deadline is None:
                    delay = poll_interval
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise WaitTimeoutError(
                            f"Hugging Face import {self.id!r} did not finish within"
                            f" {timeout} seconds (state: {self.state})."
                        )
                    delay = min(poll_interval, remaining)
                time.sleep(delay)
                self.refresh()
        except KeyboardInterrupt:
            termlog(
                f"Hugging Face import {self.id} is still running on the server."
                " Resume waiting with"
                f" wandb.Api().huggingface_import({self.id!r}).wait()."
            )
            raise

        if self.state in ("FAILED", "STOPPED"):
            raise HuggingFaceImportError(
                import_id=self.id,
                state=self.state,
                error_code=self.error_code,
                error_message=self.error_message,
            )
        return self

    def artifact(self) -> Artifact | None:
        """The imported artifact, or `None` until the import produces one."""
        from wandb.sdk.artifacts.artifact import Artifact

        if (artifact := self._current.artifact) is None:
            return None
        return Artifact._from_id(artifact.id, self._service_api)

    def registry_artifact(self) -> Artifact | None:
        """The linked registry version, or `None` until the import produces one."""
        from wandb.sdk.artifacts._validators import FullArtifactPath
        from wandb.sdk.artifacts.artifact import Artifact

        if (ref := self._current.registry_ref) is None:
            return None
        prefix, project, name = ref.split("/", 2)
        return Artifact._from_name(
            path=FullArtifactPath(prefix=prefix, project=project, name=name),
            service_api=self._service_api,
        )

    def __repr__(self) -> str:
        return f"<HuggingFaceImport {self.id} ({self.repo_id}, {self.state})>"


class HuggingFaceImports(
    RelayPaginator["RegistryHuggingFaceImportFragment", HuggingFaceImport]
):
    """A lazy iterator of `HuggingFaceImport` objects.

    Returned by `Api.huggingface_imports()`.
    """

    QUERY: ClassVar[str | None] = None
    last_response: Connection[RegistryHuggingFaceImportFragment] | None

    def __init__(
        self,
        service_api: ServiceApi,
        variables: dict[str, Any],
        per_page: int = 50,
        start: str | None = None,
    ):
        if self.QUERY is None:
            from wandb.sdk.artifacts._generated import REGISTRY_HUGGING_FACE_IMPORTS_GQL

            type(self).QUERY = REGISTRY_HUGGING_FACE_IMPORTS_GQL

        super().__init__(
            service_api, variables=variables, per_page=per_page, start=start
        )

    @override
    def _update_response(self) -> None:
        """Fetch and parse the response data for the current page."""
        from wandb._pydantic import Connection
        from wandb.sdk.artifacts._generated import RegistryHuggingFaceImports

        result = self._execute_query(
            parse=RegistryHuggingFaceImports.model_validate_json
        )
        if not (
            (org := result.organization) and (conn := org.registry_hugging_face_imports)
        ):
            raise ValueError("Unexpected response data")
        self.last_response = Connection.model_validate(conn)

    def _convert(self, node: RegistryHuggingFaceImportFragment) -> HuggingFaceImport:
        return HuggingFaceImport(self._service_api, node)
