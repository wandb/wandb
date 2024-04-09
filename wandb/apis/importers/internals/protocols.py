import logging
import sys
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from wandb.sdk.artifacts.artifact import Artifact

if sys.version_info >= (3, 8):
    from typing import Protocol, runtime_checkable
else:
    from typing_extensions import Protocol, runtime_checkable

logger = logging.getLogger("import_logger")

PathStr = str
Policy = Literal["now", "end", "live"]


@runtime_checkable
class ImporterRun(Protocol):
    def run_id(self) -> str: ...  # pragma: no cover

    def entity(self) -> str: ...  # pragma: no cover

    def project(self) -> str: ...  # pragma: no cover

    def config(self) -> Dict[str, Any]: ...  # pragma: no cover

    def summary(self) -> Dict[str, float]: ...  # pragma: no cover

    def metrics(self) -> Iterable[Dict[str, float]]:
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

    def run_group(self) -> Optional[str]: ...  # pragma: no cover

    def job_type(self) -> Optional[str]: ...  # pragma: no cover

    def display_name(self) -> str: ...  # pragma: no cover

    def notes(self) -> Optional[str]: ...  # pragma: no cover

    def tags(self) -> Optional[List[str]]: ...  # pragma: no cover

    def artifacts(self) -> Optional[Iterable[Artifact]]: ...  # pragma: no cover

    def used_artifacts(self) -> Optional[Iterable[Artifact]]: ...  # pragma: no cover

    def os_version(self) -> Optional[str]: ...  # pragma: no cover

    def python_version(self) -> Optional[str]: ...  # pragma: no cover

    def cuda_version(self) -> Optional[str]: ...  # pragma: no cover

    def program(self) -> Optional[str]: ...  # pragma: no cover

    def host(self) -> Optional[str]: ...  # pragma: no cover

    def username(self) -> Optional[str]: ...  # pragma: no cover

    def executable(self) -> Optional[str]: ...  # pragma: no cover

    def gpus_used(self) -> Optional[str]: ...  # pragma: no cover

    def cpus_used(self) -> Optional[int]: ...  # pragma: no cover

    def memory_used(self) -> Optional[int]: ...  # pragma: no cover

    def runtime(self) -> Optional[int]: ...  # pragma: no cover

    def start_time(self) -> Optional[int]: ...  # pragma: no cover

    def code_path(self) -> Optional[str]: ...  # pragma: no cover

    def cli_version(self) -> Optional[str]: ...  # pragma: no cover

    def files(
        self,
    ) -> Optional[Iterable[Tuple[PathStr, Policy]]]: ...  # pragma: no cover

    def logs(self) -> Optional[Iterable[str]]: ...  # pragma: no cover
