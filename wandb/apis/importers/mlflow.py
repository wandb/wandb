from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, Optional

from packaging.version import Version
from tqdm.auto import tqdm

import wandb
from wandb.util import coalesce, get_module

from .base import ImporterRun, send_run_with_send_manager

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


class MlflowImporter:
    def __init__(self, mlflow_tracking_uri, mlflow_registry_uri=None) -> None:
        self.mlflow_tracking_uri = mlflow_tracking_uri

        mlflow.set_tracking_uri(self.mlflow_tracking_uri)
        if mlflow_registry_uri:
            mlflow.set_registry_uri(mlflow_registry_uri)
        self.mlflow_client = mlflow.tracking.MlflowClient(mlflow_tracking_uri)

    def collect_runs(self, limit: Optional[int] = None) -> Iterable[MlflowRun]:
        if mlflow_version < Version("1.28.0"):
            experiments = self.mlflow_client.list_experiments()
        else:
            experiments = self.mlflow_client.search_experiments()

        runs = (
            run
            for exp in experiments
            for run in self.mlflow_client.search_runs(exp.experiment_id)
        )
        for i, run in enumerate(runs):
            if limit and i >= limit:
                break
            yield MlflowRun(run, self.mlflow_client)

    def import_run(
        self,
        run: ImporterRun,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        mlflow.set_tracking_uri(self.mlflow_tracking_uri)
        send_run_with_send_manager(run, overrides)

    def import_runs(
        self,
        runs: Iterable[ImporterRun],
        overrides: Optional[Dict[str, Any]] = None,
        pool_kwargs: Optional[Dict[str, Any]] = None,
    ):
        runs = list(self.collect_runs())
        overrides = coalesce(overrides, {})
        pool_kwargs = coalesce(pool_kwargs, {})

        with ThreadPoolExecutor(**pool_kwargs) as exc:
            futures = {
                exc.submit(self.import_run, run, overrides=overrides): run
                for run in runs
            }
            with tqdm(desc="Importing runs", total=len(futures), unit="run") as pbar:
                for future in as_completed(futures):
                    run = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        wandb.termerror(f"Failed to import {run.display_name()}: {e}")
                        raise e
                    else:
                        pbar.set_description(
                            f"Imported Run: {run.run_group()} {run.display_name()}"
                        )
                    finally:
                        pbar.update(1)

    def import_all_runs(
        self,
        limit: Optional[int] = None,
        overrides: Optional[Dict[str, Any]] = None,
        pool_kwargs: Optional[Dict[str, Any]] = None,
    ):
        runs = self.collect_runs(limit)
        self.import_runs(runs, overrides, pool_kwargs)

    def import_report(self):
        raise NotImplementedError("MLFlow does not have a reports concept")
