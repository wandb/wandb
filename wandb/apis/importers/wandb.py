import itertools
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime as dt
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from unittest.mock import patch

import requests
import yaml

import wandb
from wandb.apis.public import Run
from wandb.util import coalesce, get_module, remove_keys_with_none_values

with patch("click.echo"):
    import wandb.apis.reports as wr
    from wandb.apis.reports import Report

from . import internal, progress, protocols
from .config import ImportConfig
from .logs import _thread_local_settings, wandb_logger
from .protocols import ArtifactSequence

pl = get_module(
    "polars",
    required="Missing `polars`, try `pip install polars`",
)

rich = get_module(
    "rich",
    required="Missing `rich`, try `pip install rich`",
)


class WandbRun:
    def __init__(self, run: Run):
        self.run = run
        self.api = wandb.Api(
            api_key=_thread_local_settings.api_key,
            overrides={"base_url": _thread_local_settings.base_url},
        )

        _thread_local_settings.entity = self.entity()
        _thread_local_settings.project = self.project()
        _thread_local_settings.run_id = self.run_id()

        # For caching
        self._files: Optional[Iterable[Tuple[str, str]]] = None
        self._artifacts: Optional[Iterable[wandb.Artifact]] = None
        self._used_artifacts: Optional[Iterable[wandb.Artifact]] = None

    def run_id(self) -> str:
        return self.run.id

    def entity(self) -> str:
        return self.run.entity

    def project(self) -> str:
        return self.run.project

    def config(self) -> Dict[str, Any]:
        return self.run.config

    def summary(self) -> Dict[str, float]:
        s = self.run.summary

        # Modify artifact paths because they are different between systems
        s = self._modify_table_artifact_paths(s)
        return s

    def metrics(self) -> Iterable[Dict[str, float]]:
        if self._artifacts is not None:
            yield from self._artifacts
            return

        try:
            self._artifacts = list(self.run.logged_artifacts())
        except Exception as e:
            wandb_logger.error(
                f"Error downloading artifacts -- {e}",
                extra={
                    "entity": self.entity(),
                    "project": self.project(),
                    "run_id": self.run_id(),
                },
            )
            return []

        self.history_paths = []
        for art in self._artifacts:
            if art.type != "wandb-history":
                continue
            with patch("click.echo"):
                try:
                    path = art.download()
                except Exception as e:
                    wandb_logger.error(
                        f"Error downloading metrics artifact ({art}) -- {e}",
                        extra={
                            "entity": self.entity(),
                            "project": self.project(),
                            "run_id": self.run_id(),
                        },
                    )
                    break
                else:
                    self.history_paths.append(path)
                    break

        if not self.history_paths:
            wandb_logger.warn(
                "No parquet files detected; using scan history",
                extra={
                    "entity": self.entity(),
                    "project": self.project(),
                    "run_id": self.run_id(),
                },
            )
            yield from self.run.scan_history()
            return

        for path in self.history_paths:
            for p in Path(path).glob("*.parquet"):
                df = pl.read_parquet(p)
                for row in df.iter_rows(named=True):
                    row = remove_keys_with_none_values(row)
                    yield row

    def run_group(self) -> Optional[str]:
        return self.run.group

    def job_type(self) -> Optional[str]:
        return self.run.job_type

    def display_name(self) -> str:
        return self.run.display_name

    def notes(self) -> Optional[str]:
        return self.run.notes

    def tags(self) -> Optional[List[str]]:
        return self.run.tags

    def artifacts(self) -> Optional[Iterable[wandb.Artifact]]:
        if self._artifacts is not None:
            yield from self._artifacts
            return

        try:
            self._artifacts = list(self.run.logged_artifacts())
        except Exception as e:
            wandb_logger.error(
                f"Error downloading artifacts -- {e}",
                extra={
                    "entity": self.entity(),
                    "project": self.project(),
                    "run_id": self.run_id(),
                },
            )
            return []

        for art in self._artifacts:
            name, ver = art.name.split(":v")
            with patch("click.echo"):
                try:
                    path = art.download()
                except Exception as e:
                    wandb_logger.error(
                        f"Error downloading artifact ({art}) -- {e}",
                        extra={
                            "entity": self.entity(),
                            "project": self.project(),
                            "run_id": self.run_id(),
                        },
                    )
                    continue

                # Hack: skip naming validation check for wandb-* types
                new_art = wandb.Artifact(name, "temp")
                new_art._type = art.type

                # empty artifact paths are not dirs
                if Path(path).is_dir():
                    new_art.add_dir(path)

            yield new_art

    def used_artifacts(self) -> Optional[Iterable[wandb.Artifact]]:
        if self._used_artifacts is not None:
            yield from self._used_artifacts
            return

        try:
            self._used_artifacts = list(self.run.used_artifacts())
        except Exception as e:
            wandb_logger.error(
                f"Error downloading used artifacts -- {e}",
                extra={
                    "entity": self.entity(),
                    "project": self.project(),
                    "run_id": self.run_id(),
                },
            )
            return []

        for art in self._used_artifacts:
            name, ver = art.name.split(":v")
            with patch("click.echo"):
                try:
                    path = art.download()
                except Exception as e:
                    wandb_logger.error(
                        f"Error downloading used artifact ({art}) -- {e}",
                        extra={
                            "entity": self.entity(),
                            "project": self.project(),
                            "run_id": self.run_id(),
                        },
                    )
                    continue

                # Hack: skip naming validation check for wandb-* types
                new_art = wandb.Artifact(name, "temp")
                new_art._type = art.type

                # empty artifact paths are not dirs
                new_art.add_dir(path)

            yield new_art

    def os_version(self) -> Optional[str]:
        ...

    def python_version(self) -> Optional[str]:
        fname = self._find_in_files("wandb-metadata.json")
        if fname is None:
            return None

        with open(fname) as f:
            result = json.loads(f.read())
            return result.get("python")

    def cuda_version(self) -> Optional[str]:
        ...

    def program(self) -> Optional[str]:
        ...

    def host(self) -> Optional[str]:
        fname = self._find_in_files("wandb-metadata.json")
        if fname is None:
            return None

        with open(fname) as f:
            result = json.loads(f.read())
            return result.get("host")

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
        wandb_runtime = self.run.summary.get("_wandb", {}).get("runtime")
        base_runtime = self.run.summary.get("_runtime")

        t = coalesce(wandb_runtime, base_runtime)
        if t is None:
            return t
        return int(t)

    def start_time(self) -> Optional[int]:
        t = dt.fromisoformat(self.run.created_at).timestamp()
        return int(t)

    def code_path(self) -> Optional[str]:
        fname = self._find_in_files("wandb-metadata.json")
        if fname is None:
            return None

        with open(fname) as f:
            result = json.loads(f.read())
            return "code/" + result.get("codePath", "")

    def cli_version(self) -> Optional[str]:
        fname = self._find_in_files("config.yaml")
        if fname is None:
            return None

        with open(fname) as f:
            result = yaml.safe_load(f)
            return result.get("_wandb", {}).get("value", {}).get("cli_version")

    def files(self) -> Optional[Iterable[Tuple[str, str]]]:
        files_dir = f"./wandb-importer/{self.run_id()}/files"
        if self._files is not None:
            yield from self._files
            return

        self._files = []
        for f in self.run.files():
            try:
                result = f.download(files_dir, exist_ok=True)
            except Exception as e:
                wandb_logger.error(
                    f"Error downloading file ({f}) -- {e}",
                    extra={
                        "entity": self.entity(),
                        "project": self.project(),
                        "run_id": self.run_id(),
                    },
                )
                continue
            else:
                file_and_policy = (result.name, "now")
                self._files.append(file_and_policy)
                yield file_and_policy

    def logs(self) -> Optional[Iterable[str]]:
        fname = self._find_in_files("output.log")
        if fname is None:
            return

        with open(fname) as f:
            yield from f.readlines()

    def _modify_table_artifact_paths(self, row: Dict[str, Any]) -> Dict[str, Any]:
        table_keys = []
        for k, v in row.items():
            if (
                isinstance(v, (dict, wandb.old.summary.SummarySubDict))
                and v.get("_type") == "table-file"
            ):
                table_keys.append(k)

        for table_key in table_keys:
            obj = row[table_key]["artifact_path"]
            obj_name = obj.split("/")[-1]
            art_path = f"{self.entity()}/{self.project()}/run-{self.run_id()}-{table_key}:latest"
            art = None

            # Try to pick up the artifact within 20 seconds
            for _ in range(10):
                try:
                    art = self.api.artifact(art_path, type="run_table")
                except wandb.errors.CommError:
                    wandb.termwarn(f"Waiting for artifact {art_path}...")
                    time.sleep(2)
                except Exception as e:
                    wandb_logger.error(
                        f"Error getting back artifact -- {e}",
                        extra={
                            "entity": self.entity(),
                            "project": self.project(),
                            "run_id": self.run_id(),
                        },
                    )
                else:
                    break

            # If we can't find after timeout, just skip it.
            if art is None:
                wandb_logger.error(
                    "Error getting back artifact -- Timeout exceeded",
                    extra={
                        "entity": self.entity(),
                        "project": self.project(),
                        "run_id": self.run_id(),
                    },
                )
                continue

            url = art.get_path(obj_name).ref_url()
            base, name = url.rsplit("/", 1)
            latest_art_path = f"{base}:latest/{name}"

            # replace the old url which points to an artifact on the old system
            # with a new url which points to an artifact on the new system.
            # wandb.termlog(f"{row[table_key]}")
            row[table_key]["artifact_path"] = url
            row[table_key]["_latest_artifact_path"] = latest_art_path

        return row

    def _find_in_files(self, name: str) -> Optional[str]:
        files = self.files()
        if files is None:
            return None

        for path, _ in files:
            if name in path:
                return path

        return None


class WandbImporter:
    """Import runs, reports, and artifact sequences from a source instance at `src_base_url` to a destination instance at `dst_base_url`."""

    def __init__(
        self,
        src_base_url: str,
        src_api_key: str,
        dst_base_url: str,
        dst_api_key: str,
        api_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.src_base_url = src_base_url
        self.src_api_key = src_api_key
        self.dst_base_url = dst_base_url
        self.dst_api_key = dst_api_key

        if api_kwargs is None:
            api_kwargs = {}

        self.src_api = wandb.Api(
            api_key=src_api_key, overrides={"base_url": src_base_url}, **api_kwargs
        )
        self.dst_api = wandb.Api(
            api_key=dst_api_key, overrides={"base_url": dst_base_url}, **api_kwargs
        )

        # There is probably a less redundant way of doing this
        _thread_local_settings.api_key = src_api_key
        _thread_local_settings.base_url = src_base_url

    import_runs = protocols.import_runs

    def collect_runs(
        self,
        entity: str,
        project: Optional[str] = None,
        limit: Optional[int] = None,
        skip_ids: Optional[List[str]] = None,
        start_date: Optional[str] = None,
    ) -> Iterable[WandbRun]:
        filters: Dict[str, Any] = {}
        if skip_ids is not None:
            filters["name"] = {"$nin": skip_ids}
        if start_date is not None:
            filters["createdAt"] = {"$gte": start_date}

        api = self.src_api
        projects = self._projects(entity, project)

        def runs():
            for project in projects:
                for run in api.runs(
                    f"{project.entity}/{project.name}", filters=filters
                ):
                    yield WandbRun(run)

        yield from itertools.islice(runs(), limit)

    def import_run(self, run: WandbRun, config: Optional[ImportConfig] = None) -> None:
        if config is None:
            config = ImportConfig()

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
        }

        sm_config = internal.SendManagerConfig(
            metadata=True,
            files=True,
            media=True,
            code=True,
            history=True,
            summary=True,
            terminal_output=True,
        )

        internal.send_run_with_send_manager(
            run,
            overrides=config.send_manager_overrides,
            settings_override=settings_override,
            config=sm_config,
        )

    def collect_artifact_sequences(
        self,
        entity: str,
        project: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterable[ArtifactSequence]:
        projects = self._projects(entity, project)

        def sequences():
            for project in projects:
                # the "project" in artifact_types is actually entity/project
                _project = f"{entity}/{project.name}"
                for type in self.src_api.artifact_types(_project):
                    for collection in type.collections():
                        if collection.is_sequence():
                            yield collection

        # Dedupe by sequence
        unique_sequences_map = {}
        for seq in itertools.islice(sequences(), limit):
            unique_sequences_map[(seq.name, seq.type)] = seq

        # Dedupe artifacts within sequences
        seen: Set[wandb.apis.public.ArtifactCollection] = set()
        unique_sequences = unique_sequences_map.values()
        for seq in unique_sequences:
            arts = set(seq.versions())
            new_arts = arts - seen
            # Order artifacts ascending
            yield sorted(new_arts, key=lambda a: int(a.version.lstrip("v")))
            seen = seen | arts

    def import_artifact_sequence(
        self, sequence: ArtifactSequence, config: Optional[ImportConfig] = None
    ) -> None:
        if config is None:
            config = ImportConfig()

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resumed": True,
        }

        send_manager_config = internal.SendManagerConfig(
            log_artifacts=True,
            debug_mode=config.debug_mode,
        )

        sequence = list(sequence)
        s = sequence[0]
        _type = s.type
        name, _ = s.name.split(":")

        task = progress.subtask_pbar.add_task(
            f"Artifact Sequence ({_type}/{name})", total=len(sequence)
        )
        for art in sequence:
            wandb_run = art.logged_by()
            if wandb_run is None:
                continue

            try:
                path = art.download()
            except Exception as e:
                wandb_logger.error(
                    f"Error downloading artifact {art} -- {e}",
                    extra={
                        "entity": wandb_run.entity,
                        "project": wandb_run.project,
                        "run_id": wandb_run.id,
                    },
                )
                continue

            name, _ = art.name.split(":")
            # Hack: skip naming validation check for wandb-* types
            new_art = wandb.Artifact(name, "temp")
            new_art._type = art.type
            if Path(path).is_dir():
                new_art.add_dir(path)

            run = WandbRun(wandb_run)
            internal.send_artifact_with_send_manager(
                new_art,
                run,
                overrides=config.send_manager_overrides,
                settings_override=settings_override,
                config=send_manager_config,
            )
            progress.subtask_pbar.update(task, advance=1)
        progress.subtask_pbar.remove_task(task)

    def use_artifact_sequence(
        self, sequence: ArtifactSequence, config: Optional[ImportConfig] = None
    ) -> None:
        if config is None:
            config = ImportConfig()

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resume": "true",
            "resumed": True,
        }

        send_manager_config = internal.SendManagerConfig(
            use_artifacts=True,
            debug_mode=config.debug_mode,
        )

        sequence = list(sequence)
        s = sequence[0]
        _type = s.type
        name, _ = s.name.split(":")

        task = progress.subtask_pbar.add_task(
            f"Use Artifact Sequence ({_type}/{name})", total=len(sequence)
        )
        for art in sequence:
            wandb_runs = art.used_by()
            if wandb_runs == []:
                continue

            try:
                path = art.download()
            except Exception as e:
                wandb_logger.error(
                    f"Error downloading artifact {art} -- {e}",
                    extra={
                        "entity": wandb_runs[0].entity,
                        "project": wandb_runs[0].project,
                        "run_id": wandb_runs[0].id,
                    },
                )
                continue

            name, _ = art.name.split(":")

            # Hack: skip naming validation check for wandb-* types
            new_art = wandb.Artifact(name, "temp")
            new_art._type = art.type
            if Path(path).is_dir():
                new_art.add_dir(path)

            for wandb_run in wandb_runs:
                run = WandbRun(wandb_run)
                internal.send_artifact_with_send_manager(
                    new_art,
                    run,
                    overrides=config.send_manager_overrides,
                    settings_override=settings_override,
                    config=send_manager_config,
                )
            progress.subtask_pbar.update(task, advance=1)
        progress.subtask_pbar.remove_task(task)

    def collect_reports(
        self, entity: str, project: Optional[str] = None, limit: Optional[int] = None
    ) -> Iterable[Report]:
        api = self.src_api
        projects = self._projects(entity, project)

        def reports():
            for project in projects:
                for report in api.reports(f"{project.entity}/{project.name}"):
                    yield wr.Report.from_url(report.url, api=api)

        yield from itertools.islice(reports(), limit)

    def import_report(
        self, report: Report, config: Optional[ImportConfig] = None
    ) -> None:
        if config is None:
            config = ImportConfig()

        entity = coalesce(config.entity, report.entity)
        project = coalesce(config.project, report.project)
        name = report.name
        title = report.title
        description = report.description

        api = self.dst_api

        # Testing Hack: To support multithreading import_report
        # We shouldn't need to upsert the project for every report
        try:
            api.create_project(project, entity)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 409:
                wandb.termwarn(f"{e}")

        api.client.execute(
            wr.report.UPSERT_VIEW,
            variable_values={
                "id": None,  # Is there any benefit for this to be the same as default report?
                "name": name,
                "entityName": entity,
                "projectName": project,
                "description": description,
                "displayName": title,
                "type": "runs",
                "spec": json.dumps(report.spec),
            },
        )

    def _projects(self, entity: str, project: Optional[str]):
        api = self.src_api
        if project is None:
            return api.projects(entity)
        return [api.project(project, entity)]

    def _use_artifact_sequence(
        self, sequence: ArtifactSequence, config: Optional[ImportConfig] = None
    ):
        if config is None:
            config = ImportConfig()

        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
            "resume": "true",
            "resumed": True,
        }

        send_manager_config = internal.SendManagerConfig(
            use_artifacts=True,
            debug_mode=config.debug_mode,
        )

        for art in sequence:
            wandb_run = art.used_by()
            if wandb_run is None:
                continue
            run = WandbRun(wandb_run)

            internal.send_run_with_send_manager(
                run,
                overrides=config.send_manager_overrides,
                settings_override=settings_override,
                config=send_manager_config,
            )

    def import_all(
        self,
        src_entity: str,
        dst_entity: Optional[str] = None,
        src_project: Optional[str] = None,
        dst_project: Optional[str] = None,
        max_workers: Optional[int] = None,
    ):
        """Currently supports runs, artifacts, and reports.

        If `dst_entity` is not specified, it will be the same as `src_entity`.
        If `dst_project` is not specified, it will be the same as `src_project`.
        If `src_project` is not specified, we will try to import all projects under `src_entity`.
        """
        config = ImportConfig(entity=dst_entity, project=dst_project)

        reports = self.collect_reports(src_entity, src_project)
        self.import_reports(reports, config, max_workers)

        runs = self.collect_runs(src_entity, src_project)
        self.import_runs(runs, config, max_workers)

        sequences = self.collect_artifact_sequences(src_entity, src_project)
        self.import_artifact_sequences(sequences, config, max_workers)

        sequences = self.collect_artifact_sequences(src_entity, src_project)
        self.use_artifact_sequences(sequences, config, max_workers)

    def import_artifact_sequences(
        self,
        sequences: Iterable[ArtifactSequence],
        config: Optional[ImportConfig] = None,
        max_workers: Optional[int] = None,
    ) -> None:
        with progress.live:
            with ThreadPoolExecutor(max_workers) as exc:
                futures = {
                    exc.submit(self.import_artifact_sequence, seq, config): seq
                    for seq in sequences
                }
                for future in progress.task_pbar.track(
                    as_completed(futures),
                    description="Artifact Sequences",
                    total=len(futures),
                ):
                    try:
                        future.result()
                    except Exception:
                        continue

    def use_artifact_sequences(
        self,
        sequences: Iterable[ArtifactSequence],
        config: Optional[ImportConfig] = None,
        max_workers: Optional[int] = None,
    ) -> None:
        with progress.live:
            with ThreadPoolExecutor(max_workers) as exc:
                futures = {
                    exc.submit(self.use_artifact_sequence, seq, config): seq
                    for seq in sequences
                }
                for future in progress.task_pbar.track(
                    as_completed(futures),
                    description="Use Artifact Sequences",
                    total=len(futures),
                ):
                    try:
                        future.result()
                    except Exception:
                        continue

    def import_reports(
        self,
        reports: Iterable[Report],
        config: Optional[ImportConfig] = None,
        max_workers: Optional[int] = None,
    ) -> None:
        with progress.live:
            with ThreadPoolExecutor(max_workers) as exc:
                futures = {
                    exc.submit(self.import_report, report, config): report
                    for report in reports
                }
                for future in progress.task_pbar.track(
                    as_completed(futures),
                    description="Reports",
                    total=len(futures),
                ):
                    try:
                        future.result()
                    except Exception:
                        continue
