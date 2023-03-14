from typing import Any, Dict, Iterable, Optional

from wandb.util import get_module

from .base import Importer, ImporterRun

mlflow = get_module(
    "mlflow",
    required="To use the MlflowImporter, please install mlflow: `pip install mlflow`",
)


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
        def wandbify(metrics):
            for step, t in enumerate(metrics):
                d = {m.key: m.value for m in t}
                d["_step"] = step
                yield d

        metrics = [
            self.mlflow_client.get_metric_history(self.run.info.run_id, k)
            for k in self.run.data.metrics.keys()
        ]
        metrics = zip(*metrics)  # transpose
        return wandbify(metrics)

        # Alternate: Might be slower but use less mem
        # Can't make this a generator.  See mlflow get_metric_history internals
        # https://github.com/mlflow/mlflow/blob/master/mlflow/tracking/_tracking_service/client.py#L74-L93
        # for k in self.run.data.metrics.keys():
        #     history = self.mlflow_client.get_metric_history(self.run.info.run_id, k)
        #     yield wandbify(history)

    def run_group(self):
        # this is nesting?  Parent at `run.info.tags.get("mlflow.parentRunId")`
        return f"Experiment {self.run.info.experiment_id}"

    def job_type(self):
        # Is this the right approach?
        return f"User {self.run.info.user_id}"

    def display_name(self):
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
        return self.run.info.end_time // 1_000 - self.start_time()

    def git(self):
        ...

    def artifacts(self):
        for f in self.mlflow_client.list_artifacts(self.run.info.run_id):
            dir_path = mlflow.artifacts.download_artifacts(run_id=self.run.info.run_id)
            full_path = dir_path + f.path
            yield (f.path, full_path)


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
        for exp in self.mlflow_client.search_experiments():
            for run in self.mlflow_client.search_runs(exp.experiment_id):
                yield MlflowRun(run, self.mlflow_client)
