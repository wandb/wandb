import logging
import pickle
import uuid
from datetime import datetime
from pathlib import Path

from kedro.framework.hooks import hook_impl
from kedro.io.core import DatasetError
from kedro.io.memory_dataset import MemoryDataset

import wandb

from .helper import set_wandb_metadata


class WandbLoggingHooks:
    """Kedro hooks for auto-logging to wandb.

    To enable debugging, set `KEDRO_LOGGING_CONFIG` and add to your logging.yml:
        ```
        loggers:
            WandbLoggingHooks:
                level: DEBUG
        ```
    """

    def __init__(self, *, log_memory_datasets=False, prefer_references=True):
        self.log_memory_datasets = log_memory_datasets
        self.prefer_references = prefer_references

        self._logger = logging.getLogger(self.__class__.__name__)
        self._run = None
        self._pipeline_name = None
        self._pipeline_uuid = None
        self._pipeline_time_string = None
        self._memory_dataset_tracker = []
        self._tags = ["integration:wandb_kedro"]

    @hook_impl
    def before_pipeline_run(self, run_params):
        self._pipeline_name = run_params["pipeline_name"] or ""
        self._pipeline_uuid = str(uuid.uuid4())[:8]
        self._pipeline_time_string = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._memory_dataset_tracker = []
        self._logger.debug(
            f"Starting pipeline with {self._pipeline_name=}, {self._pipeline_uuid=}, {self._pipeline_time_string=}"
        )

    @hook_impl
    def before_node_run(self, node, catalog):
        if self._run is not None:
            self._run.finish()
            self._run = None

        self._logger.debug("Collecting configs")
        configs = {
            n: catalog.load(n) for n in catalog.list() if n.startswith("config:")
        }

        self._logger.debug("Saving run metadata")
        metadata = {
            "job_type": node.name,
            "tags": self._tags
            + [
                f"node:{node.name}",
                f"pipeline:{self._pipeline_name}",
                f"pipeline_uuid:{self._pipeline_uuid}",
                f"pipeline_time:{self._pipeline_time_string}",
            ],
            "config": configs,
        }
        set_wandb_metadata(metadata)

        self._logger.debug("Starting wandb run")
        self._run = wandb.init(**metadata)

        self._logger.debug("Logging input artifacts")
        for name in node.inputs:
            self._logger.debug(f"Input {name=}")
            art = None
            if name not in catalog.list():
                continue
            if name.startswith("params:"):  # params are configs
                continue

            dataset = catalog._datasets[name]
            if isinstance(dataset, MemoryDataset):
                if not self.log_memory_datasets:
                    continue
                art = create_memory_dataset_art(name, dataset._data)
            else:
                art = create_generic_dataset_art(
                    name,
                    dataset,
                    use_references=self.prefer_references,
                )

            if art is not None:
                self._run.use_artifact(art)
        self._logger.debug("Done before node run")

    @hook_impl
    def after_node_run(self, node, catalog):
        self._logger.debug("Logging output artifacts")
        for name in node.outputs:
            self._logger.debug(f"Output {name=}")

            if name not in catalog.list():
                self._logger.debug(f"{name=} not in catalog, skipping")
                try:
                    catalog.load(name)
                except DatasetError:
                    self._memory_dataset_tracker.append(name)
                continue
            if name.startswith("params:"):  # params are configs
                self._logger.debug(f"{name=} not is param, skipping")
                continue

            dataset = catalog._datasets[name]
            if isinstance(dataset, MemoryDataset):
                self._logger.debug("This is a memory dataset")
                if not self.log_memory_datasets:
                    continue
                art = create_memory_dataset_art(name, dataset._data)
            else:
                art = create_generic_dataset_art(
                    name,
                    dataset,
                    use_references=self.prefer_references,
                )

            if art is not None:
                self._run.log_artifact(art)

        self._logger.debug("Done after node run")

    @hook_impl
    def after_pipeline_run(self):
        if self._run is not None:
            self._run.finish()
            self._run = None

    @hook_impl
    def after_dataset_saved(self, dataset_name, data):
        # We only do this for memory datasets because they aren't saved until after the node is finished.
        # Datasets are also loaded before the node starts, so this seemed like the cleanest way.
        # Ideally we could log and use datasets entirely in the before_node_run and after_node_run hooks...
        if dataset_name in self._memory_dataset_tracker and self.log_memory_datasets:
            art = create_memory_dataset_art(dataset_name, data)
            self._run.log_artifact(art)


def create_memory_dataset_art(name, data):
    art = wandb.Artifact(name, type="memory_dataset")
    fname = f"{name}.pkl"
    with open(fname, "wb") as f:
        pickle.dump(data, f)
    art.add_file(fname)
    return art


def create_generic_dataset_art(name, dataset, type="artifact", use_references=False):
    art = wandb.Artifact(name, type=type)
    path = Path(dataset._filepath)

    def add_files_recursively(directory):
        for item in directory.iterdir():
            if item.is_file():
                art.add_reference(uri=f"file://{item}", name=item.name)
            elif item.is_dir():
                add_files_recursively(item)

    if path.is_file():
        if use_references:
            art.add_reference(uri=f"file://{path}", name=path.name)
        else:
            art.add_file(str(path))
    elif path.is_dir():
        if use_references:
            add_files_recursively(path)
        else:
            art.add_dir(str(path))

    return art
