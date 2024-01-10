import logging
import os
import pickle
import uuid
from datetime import datetime

from kedro.framework.hooks import hook_impl
from kedro.io.memory_dataset import MemoryDataset
from kedro_datasets.pandas import CSVDataset, ExcelDataset, ParquetDataset

import wandb

from .helper import set_wandb_metadata


class WandbLoggingHooks:
    def __init__(self, *, log_memory_datasets=False, prefer_references=False):
        self._log_memory_dataset = log_memory_datasets
        self._prefer_references = prefer_references

        self._logger = logging.getLogger(__name__)
        self._run = None
        self._pipeline_name = None
        self._pipeline_uuid = None

        time_string = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._tags = [time_string, "wandb_kedro"]

    @staticmethod
    def create_memory_dataset_art(name, dataset):
        art = wandb.Artifact(name, type="memory_dataset")
        fname = f"{name}.pkl"
        with open(fname, "wb") as f:
            pickle.dump(dataset._data, f)
        art.add_file(fname)
        return art

    @staticmethod
    def create_generic_dataset_art(name, dataset, type="artifact"):
        art = wandb.Artifact(name, type=type)
        path = dataset._filepath
        if os.path.isfile(path):
            art.add_file(path)
        elif os.path.isdir(path):
            art.add_dir(path)
        return art

    @hook_impl
    def before_pipeline_run(self, run_params):
        self._pipeline_name = run_params["pipeline_name"] or ""
        self._pipeline_uuid = str(uuid.uuid4())[:8]

    @hook_impl
    def before_node_run(self, node, catalog):
        self._logger.debug("Collecting configs")
        configs = {
            n: catalog.load(n) for n in catalog.list() if n.startswith("config:")
        }
        node_tags = ["node:" + node.name]

        self._logger.debug("Saving run metadata")
        metadata = {
            "job_type": node.name,
            "tags": self._tags + node_tags,
            "config": configs,
        }
        set_wandb_metadata(metadata)

        self._logger.debug("Starting wandb run")
        self._run = wandb.init(**metadata)

        self._logger.debug("Logging input artifacts")
        for name in node.inputs:
            art = None
            if name not in catalog.list():
                continue
            dataset = catalog._datasets[name]
            if isinstance(dataset, MemoryDataset):
                continue
            else:
                art = self.create_generic_dataset_art(name, dataset)

            if art is not None:
                self._run.use_artifact(art)

    @hook_impl
    def after_node_run(self, node, catalog):
        self._logger.debug("Logging output artifacts")
        for name in node.inputs:
            art = None
            if name not in catalog.list():
                continue
            dataset = catalog._datasets[name]
            if isinstance(dataset, MemoryDataset):
                if not self._log_memory_dataset or name.startswith("params:"):
                    continue
                art = self.create_memory_dataset_art(name, dataset)

            if art is not None:
                self._run.use_artifact(art)

        for name in node.outputs:
            if name not in catalog.list():
                continue
            dataset = catalog._datasets[name]
            if isinstance(dataset, MemoryDataset):
                if not self._log_memory_dataset or name.startswith("params:"):
                    continue
                art = self.create_memory_dataset_art(name, dataset)
            elif isinstance(dataset, ParquetDataset):
                art = self.create_generic_dataset_art(name, dataset, type="parquet")
            elif isinstance(dataset, ExcelDataset):
                art = self.create_generic_dataset_art(name, dataset, type="excel")
            elif isinstance(dataset, CSVDataset):
                art = self.create_generic_dataset_art(name, dataset, type="csv")
            else:
                art = self.create_generic_dataset_art(name, dataset)

            if art is not None:
                self._run.log_artifact(art)

        self._run.finish()
