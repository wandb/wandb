from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, Literal, Protocol, runtime_checkable

from wandb.sdk.artifacts.artifact import Artifact

logger = logging.getLogger("import_logger")

PathStr = str
Policy = Literal["now", "end", "live"]


@runtime_checkable
class ImporterRun(Protocol):
    def run_id(self) -> str: ...  # pragma: no cover

    def entity(self) -> str: ...  # pragma: no cover

    def project(self) -> str: ...  # pragma: no cover

    def config(self) -> dict[str, Any]: ...  # pragma: no cover

    def summary(self) -> dict[str, float]: ...  # pragma: no cover

    def metrics(self) -> Iterable[dict[str, float]]:
        """Metrics for the run.

        We expect metrics in this shape:

        [
            {'metric1': 1, 'metric2': 1, '_step': 0},
            {'metric1': 2, 'metric2': 4, '_step': 1},
            {'metric1': 3, 'metric2': 9, '_step': 2},
            ...
        ]

        You can also submit metrics in this shape:
        [
            {'metric1': 1, '_step': 0},
            {'metric2': 1, '_step': 0},
            {'metric1': 2, '_step': 1},
            {'metric2': 4, '_step': 1},
            ...
        ]
        """
        ...  # pragma: no cover

    def run_group(self) -> str | None: ...  # pragma: no cover

    def job_type(self) -> str | None: ...  # pragma: no cover

    def display_name(self) -> str: ...  # pragma: no cover

    def notes(self) -> str | None: ...  # pragma: no cover

    def tags(self) -> list[str] | None: ...  # pragma: no cover

    def artifacts(self) -> Iterable[Artifact] | None: ...  # pragma: no cover

    def used_artifacts(self) -> Iterable[Artifact] | None: ...  # pragma: no cover

    def os_version(self) -> str | None: ...  # pragma: no cover

    def python_version(self) -> str | None: ...  # pragma: no cover

    def cuda_version(self) -> str | None: ...  # pragma: no cover

    def program(self) -> str | None: ...  # pragma: no cover

    def host(self) -> str | None: ...  # pragma: no cover

    def username(self) -> str | None: ...  # pragma: no cover

    def executable(self) -> str | None: ...  # pragma: no cover

    def gpus_used(self) -> str | None: ...  # pragma: no cover

    def cpus_used(self) -> int | None: ...  # pragma: no cover

    def memory_used(self) -> int | None: ...  # pragma: no cover

    def runtime(self) -> int | None: ...  # pragma: no cover

    def start_time(self) -> int | None: ...  # pragma: no cover

    def code_path(self) -> str | None: ...  # pragma: no cover

    def cli_version(self) -> str | None: ...  # pragma: no cover

    def files(
        self,
    ) -> Iterable[tuple[PathStr, Policy]] | None: ...  # pragma: no cover

    def logs(self) -> Iterable[str] | None: ...  # pragma: no cover
