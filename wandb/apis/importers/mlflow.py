from __future__ import annotations

import itertools
import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

import mlflow
from packaging.version import Version  # type: ignore

import wandb
from wandb import Artifact

from .internals import internal
from .internals.util import Namespace, for_each

mlflow_version = Version(mlflow.__version__)

logger = logging.getLogger("import_logger")


class MlflowRun:
    def __init__(self, run, mlflow_client):
        self.run = run
        self.mlflow_client: mlflow.MlflowClient = mlflow_client

    def run_id(self) -> str:
        return self.run.info.run_id

    def entity(self) -> str:
        return self.run.info.user_id

    def project(self) -> str:
        return "imported-from-mlflow"

    def config(self) -> dict[str, Any]:
        conf = self.run.data.params

        # Add tags here since mlflow supports very long tag names but we only support up to 64 chars
        tags = {
            k: v for k, v in self.run.data.tags.items() if not k.startswith("mlflow.")
        }
        return {**conf, "imported_mlflow_tags": tags}

    def summary(self) -> dict[str, float]:
        return self.run.data.metrics

    def metrics(self) -> Iterable[dict[str, float]]:
        d: dict[int, dict[str, float]] = defaultdict(dict)
        for k in self.run.data.metrics.keys():
            metric = self.mlflow_client.get_metric_history(self.run.info.run_id, k)
            for item in metric:
                d[item.step][item.key] = item.value

        for k, v in d.items():
            yield {"_step": k, **v}

    def run_group(self) -> str | None:
        # this is nesting?  Parent at `run.info.tags.get("mlflow.parentRunId")`
        return f"Experiment {self.run.info.experiment_id}"

    def job_type(self) -> str | None:
        # Is this the right approach?
        return f"User {self.run.info.user_id}"

    def display_name(self) -> str:
        if mlflow_version < Version("1.30.0"):
            return self.run.data.tags["mlflow.runName"]
        return self.run.info.run_name

    def notes(self) -> str | None:
        return self.run.data.tags.get("mlflow.note.content")

    def tags(self) -> list[str] | None:
        ...

        # W&B tags are different than mlflow tags.
        # The full mlflow tags are added to config under key `imported_mlflow_tags` instead

    def artifacts(self) -> Iterable[Artifact] | None:  # type: ignore
        if mlflow_version < Version("2.0.0"):
            dir_path = self.mlflow_client.download_artifacts(
                run_id=self.run.info.run_id,
                path="",
            )
        else:
            dir_path = mlflow.artifacts.download_artifacts(run_id=self.run.info.run_id)

        # Since mlflow doesn't have extra metadata about the artifacts,
        # we just lump them all together into a single wandb.Artifact
        artifact_name = self._handle_incompatible_strings(self.display_name())
        art = wandb.Artifact(artifact_name, "imported-artifacts")
        art.add_dir(dir_path)

        return [art]

    def used_artifacts(self) -> Iterable[Artifact] | None:  # type: ignore
        ...  # pragma: no cover

    def os_version(self) -> str | None: ...  # pragma: no cover

    def python_version(self) -> str | None: ...  # pragma: no cover

    def cuda_version(self) -> str | None: ...  # pragma: no cover

    def program(self) -> str | None: ...  # pragma: no cover

    def host(self) -> str | None: ...  # pragma: no cover

    def username(self) -> str | None: ...  # pragma: no cover

    def executable(self) -> str | None: ...  # pragma: no cover

    def gpus_used(self) -> str | None: ...  # pragma: no cover

    def cpus_used(self) -> int | None:  # can we get the model?
        ...  # pragma: no cover

    def memory_used(self) -> int | None: ...  # pragma: no cover

    def runtime(self) -> int | None:
        end_time = (
            self.run.info.end_time // 1000
            if self.run.info.end_time is not None
            else self.start_time()
        )
        return end_time - self.start_time()

    def start_time(self) -> int | None:
        return self.run.info.start_time // 1000

    def code_path(self) -> str | None: ...  # pragma: no cover

    def cli_version(self) -> str | None: ...  # pragma: no cover

    def files(self) -> Iterable[tuple[str, str]] | None: ...  # pragma: no cover

    def logs(self) -> Iterable[str] | None: ...  # pragma: no cover

    @staticmethod
    def _handle_incompatible_strings(s: str) -> str:
        valid_chars = r"[^a-zA-Z0-9_\-\.]"
        replacement = "__"

        return re.sub(valid_chars, replacement, s)


class MlflowImporter:
    def __init__(
        self,
        dst_base_url: str,
        dst_api_key: str,
        mlflow_tracking_uri: str,
        mlflow_registry_uri: str | None = None,
        *,
        custom_api_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.dst_base_url = dst_base_url
        self.dst_api_key = dst_api_key

        if custom_api_kwargs is None:
            custom_api_kwargs = {"timeout": 600}

        self.dst_api = wandb.Api(
            api_key=dst_api_key,
            overrides={"base_url": dst_base_url},
            **custom_api_kwargs,
        )
        self.mlflow_tracking_uri = mlflow_tracking_uri
        mlflow.set_tracking_uri(self.mlflow_tracking_uri)

        if mlflow_registry_uri:
            mlflow.set_registry_uri(mlflow_registry_uri)

        self.mlflow_client = mlflow.tracking.MlflowClient(mlflow_tracking_uri)

    def __repr__(self):
        return f"<MlflowImporter src={self.mlflow_tracking_uri}>"

    def collect_runs(self, *, limit: int | None = None) -> Iterable[MlflowRun]:
        if mlflow_version < Version("1.28.0"):
            experiments = self.mlflow_client.list_experiments()
        else:
            experiments = self.mlflow_client.search_experiments()

        def _runs():
            for exp in experiments:
                for run in self.mlflow_client.search_runs(exp.experiment_id):
                    yield MlflowRun(run, self.mlflow_client)

        runs = itertools.islice(_runs(), limit)
        yield from runs

    def _import_run(
        self,
        run: MlflowRun,
        *,
        artifacts: bool = True,
        namespace: Namespace | None = None,
        config: internal.SendManagerConfig | None = None,
    ) -> None:
        if namespace is None:
            namespace = Namespace(run.entity(), run.project())

        if config is None:
            config = internal.SendManagerConfig(
                metadata=True,
                files=True,
                media=True,
                code=True,
                history=True,
                summary=True,
                terminal_output=True,
            )

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resume": "allow",
            "resumed": True,
        }

        mlflow.set_tracking_uri(self.mlflow_tracking_uri)
        internal.send_run(
            run,
            overrides=namespace.send_manager_overrides,
            settings_override=settings_override,
            config=config,
        )

        # in mlflow, the artifacts come with the runs, so import them together
        if artifacts:
            arts = list(run.artifacts())
            logger.debug(f"Importing history artifacts, {run=}")
            internal.send_run(
                run,
                extra_arts=arts,
                overrides=namespace.send_manager_overrides,
                settings_override=settings_override,
                config=internal.SendManagerConfig(log_artifacts=True),
            )

    def import_runs(
        self,
        runs: Iterable[MlflowRun],
        *,
        artifacts: bool = True,
        namespace: Namespace | None = None,
        parallel: bool = True,
        max_workers: int | None = None,
    ) -> None:
        def _import_run_wrapped(run):
            self._import_run(run, namespace=namespace, artifacts=artifacts)

        for_each(_import_run_wrapped, runs, parallel=parallel, max_workers=max_workers)
