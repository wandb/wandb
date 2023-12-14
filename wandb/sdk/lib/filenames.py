import os
from typing import Callable, Generator, Union

WANDB_DIRS = ("wandb", ".wandb")

CONFIG_FNAME = "config.yaml"
OUTPUT_FNAME = "output.log"
DIFF_FNAME = "diff.patch"
SUMMARY_FNAME = "wandb-summary.json"
METADATA_FNAME = "wandb-metadata.json"
REQUIREMENTS_FNAME = "requirements.txt"
HISTORY_FNAME = "wandb-history.jsonl"
EVENTS_FNAME = "wandb-events.jsonl"
JOBSPEC_FNAME = "wandb-jobspec.json"
CONDA_ENVIRONMENTS_FNAME = "conda-environment.yaml"


def is_wandb_file(name: str) -> bool:
    return (
        name.startswith("wandb")
        or name == METADATA_FNAME
        or name == CONFIG_FNAME
        or name == REQUIREMENTS_FNAME
        or name == OUTPUT_FNAME
        or name == DIFF_FNAME
        or name == CONDA_ENVIRONMENTS_FNAME
    )


def filtered_dir(
    root: str,
    include_fn: Union[Callable[[str, str], bool], Callable[[str], bool]],
    exclude_fn: Union[Callable[[str, str], bool], Callable[[str], bool]],
) -> Generator[str, None, None]:
    """Simple generator to walk a directory."""
    import inspect

    # compatibility with old API, which didn't pass root
    def _include_fn(path: str, root: str) -> bool:
        return (
            include_fn(path, root)  # type: ignore
            if len(inspect.signature(include_fn).parameters) == 2
            else include_fn(path)  # type: ignore
        )

    def _exclude_fn(path: str, root: str) -> bool:
        return (
            exclude_fn(path, root)  # type: ignore
            if len(inspect.signature(exclude_fn).parameters) == 2
            else exclude_fn(path)  # type: ignore
        )

    for dirpath, _, files in os.walk(root):
        for fname in files:
            file_path = os.path.join(dirpath, fname)
            if _include_fn(file_path, root) and not _exclude_fn(file_path, root):
                yield file_path


def exclude_wandb_fn(path: str, root: str) -> bool:
    return any(
        os.path.relpath(path, root).startswith(wandb_dir + os.sep)
        for wandb_dir in WANDB_DIRS
    )
