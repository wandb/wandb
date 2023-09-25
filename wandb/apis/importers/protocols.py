import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, Iterable, Iterator, List, Optional, Tuple

import wandb

if sys.version_info >= (3, 8):
    from typing import Protocol, runtime_checkable
else:
    from typing_extensions import Protocol, runtime_checkable

import traceback

from . import progress
from .config import Namespace


@dataclass
class ArtifactSequence:
    artifacts: Iterable[wandb.Artifact]
    entity: str
    project: str

    name: str = field(init=False)

    def __post_init__(self):
        self.artifacts = list(self.artifacts)
        if self.artifacts:
            self.name = self.artifacts[0].name
        else:
            self.name = ""

    def __iter__(self) -> Iterator:
        return iter(self.artifacts)


@runtime_checkable
class ImporterRun(Protocol):
    def run_id(self) -> str:
        ...

    def entity(self) -> str:
        ...

    def project(self) -> str:
        ...

    def config(self) -> Dict[str, Any]:
        ...

    def summary(self) -> Dict[str, float]:
        ...

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
        ...

    def run_group(self) -> Optional[str]:
        ...

    def job_type(self) -> Optional[str]:
        ...

    def display_name(self) -> str:
        ...

    def notes(self) -> Optional[str]:
        ...

    def tags(self) -> Optional[List[str]]:
        ...

    def artifacts(self) -> Optional[Iterable[wandb.Artifact]]:
        ...

    def used_artifacts(self) -> Optional[Iterable[wandb.Artifact]]:
        ...

    def os_version(self) -> Optional[str]:
        ...

    def python_version(self) -> Optional[str]:
        ...

    def cuda_version(self) -> Optional[str]:
        ...

    def program(self) -> Optional[str]:
        ...

    def host(self) -> Optional[str]:
        ...

    def username(self) -> Optional[str]:
        ...

    def executable(self) -> Optional[str]:
        ...

    def gpus_used(self) -> Optional[str]:
        ...

    def cpus_used(self) -> Optional[int]:  # can we get the model?
        ...

    def memory_used(self) -> Optional[int]:
        ...

    def runtime(self) -> Optional[int]:
        ...

    def start_time(self) -> Optional[int]:
        ...

    def code_path(self) -> Optional[str]:
        ...

    def cli_version(self) -> Optional[str]:
        ...

    def files(self) -> Optional[Iterable[Tuple[str, str]]]:
        ...

    def logs(self) -> Optional[Iterable[str]]:
        ...


@runtime_checkable
class Importer(Protocol):
    def collect_runs(self, *args: Any, **kwargs: Any) -> Iterable[ImporterRun]:
        ...

    def import_run(self, run: ImporterRun, config: Optional[Namespace]) -> None:
        ...


def import_runs(
    importer,
    runs: Iterable[ImporterRun],
    namespace: Optional[Namespace] = None,
    max_workers: Optional[int] = None,
) -> None:
    """Import a collection of runs.

    Use `config` to specify alternate settings like where the report should be uploaded

    Optional:
    - `max_workers` -- set number of worker threads
    """
    parallelize(
        importer._import_run,
        runs,
        namespace=namespace,
        max_workers=max_workers,
        description="Runs",
    )


def parallelize(
    func,
    iterable: Iterable,
    *args,
    description: str,
    max_workers: Optional[int] = None,
    accumulate: bool = False,
    **kwargs,
):
    results = []
    progress.live.start()
    with ThreadPoolExecutor(max_workers) as exc:
        futures = {exc.submit(func, x, *args, **kwargs): x for x in iterable}
        task = progress.task_pbar.add_task(description, total=len(futures))
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                run = futures[future]
                _, _, exc_traceback = sys.exc_info()
                traceback_details = traceback.extract_tb(exc_traceback)
                filename = traceback_details[-1].filename
                lineno = traceback_details[-1].lineno
                print(
                    f"Exception: {run=} {e=} {filename=} {lineno=}. {traceback_details=}"
                )
                continue
            else:
                results.append(result)
            finally:
                progress.task_pbar.update(task, advance=1, refresh=True)
        progress.task_pbar.update(task, completed=len(futures), refresh=True)

    return results
