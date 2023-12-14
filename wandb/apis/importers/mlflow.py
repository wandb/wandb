import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple
from unittest.mock import patch

from packaging.version import Version  # type: ignore
from tqdm.auto import tqdm

import wandb
from wandb import Artifact
from wandb.util import coalesce, get_module

from .base import ImporterRun, send_run_with_send_manager

with patch("click.echo"):
    from wandb.apis.reports import Report

mlflow = get_module(
    "mlflow",
    required="To use the MlflowImporter, please install mlflow: `pip install mlflow`",
)

mlflow_version = Version(mlflow.__version__)


class MlflowRun:
    def __init__(self, run, mlflow_client):
        self.run = run
        self.mlflow_client = mlflow_client

    def run_id(self) -> str:
        return self.run.info.run_id

    def entity(self) -> str:
        return self.run.info.user_id

    def project(self) -> str:
        return "imported-from-mlflow"

    def config(self) -> Dict[str, Any]:
        return self.run.data.params

    def summary(self) -> Dict[str, float]:
        return self.run.data.metrics

    def metrics(self) -> Iterable[Dict[str, float]]:
        d: Dict[int, Dict[str, float]] = defaultdict(dict)
        for k in self.run.data.metrics.keys():
            metric = self.mlflow_client.get_metric_history(self.run.info.run_id, k)
            for item in metric:
                d[item.step][item.key] = item.value

        for k, v in d.items():
            yield {"_step": k, **v}

    def run_group(self) -> Optional[str]:
        # this is nesting?  Parent at `run.info.tags.get("mlflow.parentRunId")`
        return f"Experiment {self.run.info.experiment_id}"

    def job_type(self) -> Optional[str]:
        # Is this the right approach?
        return f"User {self.run.info.user_id}"

    def display_name(self) -> str:
        if mlflow_version < Version("1.30.0"):
            return self.run.data.tags["mlflow.runName"]
        return self.run.info.run_name

    def notes(self) -> Optional[str]:
        return self.run.data.tags.get("mlflow.note.content")

    def tags(self) -> Optional[List[str]]:
        mlflow_tags = {
            k: v for k, v in self.run.data.tags.items() if not k.startswith("mlflow.")
        }
        return [f"{k}={v}" for k, v in mlflow_tags.items()]

    def artifacts(self) -> Optional[Iterable[Artifact]]:  # type: ignore
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

    def used_artifacts(self) -> Optional[Iterable[Artifact]]:  # type: ignore
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
        end_time = (
            self.run.info.end_time // 1000
            if self.run.info.end_time is not None
            else self.start_time()
        )
        return end_time - self.start_time()

    def start_time(self) -> Optional[int]:
        return self.run.info.start_time // 1000

    def code_path(self) -> Optional[str]:
        ...

    def cli_version(self) -> Optional[str]:
        ...

    def files(self) -> Optional[Iterable[Tuple[str, str]]]:
        ...

    def logs(self) -> Optional[Iterable[str]]:
        ...

    @staticmethod
    def _handle_incompatible_strings(s: str) -> str:
        valid_chars = r"[^a-zA-Z0-9_\-\.]"
        replacement = "__"

        return re.sub(valid_chars, replacement, s)


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
    ) -> None:
        _overrides = coalesce(overrides, {})
        _pool_kwargs = coalesce(pool_kwargs, {})
        runs = list(self.collect_runs())

        with ThreadPoolExecutor(**_pool_kwargs) as exc:
            futures = {
                exc.submit(self.import_run, run, overrides=_overrides): run
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
    ) -> None:
        runs = self.collect_runs(limit)
        self.import_runs(runs, overrides, pool_kwargs)

    def import_report(self, report: Report):
        raise NotImplementedError("MLFlow does not have a reports concept")
