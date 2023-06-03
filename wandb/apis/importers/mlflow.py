from collections import defaultdict
from typing import Any, Dict, Iterable, Optional

from packaging.version import Version

import wandb
from wandb.util import get_module

from .base import Importer, ImporterRun

mlflow = get_module(
    "mlflow",
    required="To use the MlflowImporter, please install mlflow: `pip install mlflow`",
)

mlflow_version = Version(mlflow.__version__)


class MlflowRun(ImporterRun):
    def __init__(self, run, mlflow_client):
        self.run = run
        self.mlflow_client = mlflow_client
        super().__init__()

    def run_id(self):
        return self.run.info.run_id

    def entity(self):
        return self.run.info.user_id

    def project(self):
        return "imported-from-mlflow"

    def config(self):
        return self.run.data.params

    def summary(self):
        return self.run.data.metrics

    def metrics(self):
        d = defaultdict(dict)
        metrics = (
            self.mlflow_client.get_metric_history(self.run.info.run_id, k)
            for k in self.run.data.metrics.keys()
        )
        for metric in metrics:
            for item in metric:
                d[item.step][item.key] = item.value

        flattened = ({"_step": k, **v} for k, v in d.items())
        return flattened

    def run_group(self):
        # this is nesting?  Parent at `run.info.tags.get("mlflow.parentRunId")`
        return f"Experiment {self.run.info.experiment_id}"

    def job_type(self):
        # Is this the right approach?
        return f"User {self.run.info.user_id}"

    def display_name(self):
        if mlflow_version < Version("1.30.0"):
            return self.run.data.tags["mlflow.runName"]

        return self.run.info.run_name

    def notes(self):
        return self.run.data.tags.get("mlflow.note.content")

    def tags(self):
        return {
            k: v for k, v in self.run.data.tags.items() if not k.startswith("mlflow.")
        }

    def start_time(self):
        return self.run.info.start_time // 1000

    def runtime(self):
        end_time = (
            self.run.info.end_time // 1000
            if self.run.info.end_time is not None
            else self.start_time()
        )

        return end_time - self.start_time()

    def git(self):
        ...

    def artifacts(self):
        if mlflow_version < Version("2.0.0"):
            dir_path = self.mlflow_client.download_artifacts(
                run_id=self.run.info.run_id, path=""
            )
        else:
            dir_path = mlflow.artifacts.download_artifacts(run_id=self.run.info.run_id)

        artifact_name = self._handle_incompatible_strings(self.display_name())
        art = wandb.Artifact(artifact_name, "imported-artifacts")
        art.add_dir(dir_path)

        return [art]


class MlflowImporter(Importer):
    def __init__(
        self, mlflow_tracking_uri, mlflow_registry_uri=None, wandb_base_url=None
    ) -> None:
        super().__init__()
        self.mlflow_tracking_uri = mlflow_tracking_uri

        mlflow.set_tracking_uri(self.mlflow_tracking_uri)
        if mlflow_registry_uri:
            mlflow.set_registry_uri(mlflow_registry_uri)
        self.mlflow_client = mlflow.tracking.MlflowClient(mlflow_tracking_uri)

    def import_one(
        self,
        run: ImporterRun,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        mlflow.set_tracking_uri(self.mlflow_tracking_uri)
        super().import_one(run, overrides)

    def download_all_runs(self) -> Iterable[MlflowRun]:
        if mlflow_version < Version("1.28.0"):
            experiments = self.mlflow_client.list_experiments()
        else:
            experiments = self.mlflow_client.search_experiments()

        for exp in experiments:
            for run in self.mlflow_client.search_runs(exp.experiment_id):
                yield MlflowRun(run, self.mlflow_client)
