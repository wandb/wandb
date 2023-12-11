import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime as dt
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple
from unittest.mock import patch

import requests
import yaml

import wandb
from wandb.apis.public import Run
from wandb.util import coalesce, get_module, remove_keys_with_none_values

from .base import (
    _thread_local_settings,
    send_run_with_send_manager,
    set_thread_local_settings,
)

with patch("click.echo"):
    import wandb.apis.reports as wr
    from wandb.apis.reports import Report

pl = get_module(
    "polars",
    required="To use the WandbImporter, please install polars: `pip install polars`",
)

_tqdm = get_module(
    "tqdm",
    required="To use the WandbImporter, please install tqdm: `pip install tqdm`",
)
tqdm = _tqdm.tqdm


class WandbRun:
    def __init__(self, run: Run):
        self.run = run
        self.api = wandb.Api(
            api_key=_thread_local_settings.api_key,
            overrides={"base_url": _thread_local_settings.base_url},
        )

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

        # Hack: We need to overwrite the artifact path for tables
        # because they are different between systems!
        s = self._modify_table_artifact_paths(s)
        return s

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
        return self.run.scan_history()

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
        arts = self.run.logged_artifacts()
        for art in tqdm(arts, "Logged artifacts", leave=False, unit="art"):
            name, ver = art.name.split(":v")
            try:
                with patch("click.echo"):
                    path = art.download()
            except Exception as e:
                wandb.termerror(f"Skipping artifact: {e}")
                continue

            # Hack: skip naming validation check for wandb-* types
            new_art = wandb.Artifact(name, "temp")
            new_art._type = art.type
            with patch("click.echo"):
                new_art.add_dir(path)

            yield new_art

    def used_artifacts(self) -> Optional[Iterable[wandb.Artifact]]:
        arts = self.run.used_artifacts()
        for art in tqdm(arts, "Used artifacts", leave=False, unit="art"):
            name, ver = art.name.split(":v")
            try:
                with patch("click.echo"):
                    path = art.download()
            except Exception as e:
                wandb.termerror(f"Skipping artifact: {e}")
                continue

            # Hack: skip naming validation check for wandb-* types
            new_art = wandb.Artifact(name, "temp")
            new_art._type = art.type
            with patch("click.echo"):
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
        run_dir = f"./wandb-importer/{self.run_id()}"
        base_path = f"{run_dir}/files"
        files = self.run.files()
        for f in tqdm(files, "Files", leave=False, unit="file"):
            try:
                result = f.download(base_path, exist_ok=True)
            except Exception as e:
                wandb.termerror(
                    f"Problem in run {self.run_id()}({self.display_name()}) downloading file {f}: {e}"
                )
                continue
            else:
                yield (result.name, "now")

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
                else:
                    break

            # If we can't find after timeout, just skip it.
            if art is None:
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
    DefaultRunClass = WandbRun

    def __init__(
        self,
        src_base_url: str,
        src_api_key: str,
        dst_base_url: str,
        dst_api_key: str,
    ) -> None:
        self.src_base_url = src_base_url
        self.src_api_key = src_api_key
        self.dst_base_url = dst_base_url
        self.dst_api_key = dst_api_key

        self.src_api = wandb.Api(
            api_key=src_api_key,
            overrides={"base_url": src_base_url},
        )
        self.dst_api = wandb.Api(
            api_key=dst_api_key,
            overrides={"base_url": dst_base_url},
        )

        # There is probably a less redundant way of doing this
        set_thread_local_settings(src_api_key, src_base_url)

    def collect_runs(
        self,
        entity: str,
        project: Optional[str] = None,
        limit: Optional[int] = None,
        skip_ids: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Generator[WandbRun, None, None]:
        if filters is None:
            filters = {}
        if skip_ids is not None:
            filters["name"] = {"$nin": skip_ids}
        if start_date is not None:
            filters["createdAt"] = {"$gte": start_date}

        api = self.src_api
        projects = self._projects(entity, project)

        runs = (
            run
            for project in projects
            for run in api.runs(f"{project.entity}/{project.name}", filters=filters)
        )
        for i, run in enumerate(runs):
            if limit and i >= limit:
                break
            yield self.DefaultRunClass(run)

    def import_run(
        self,
        run: WandbRun,
        overrides: Optional[Dict[str, Any]] = None,
        rewind_steps: Optional[int] = 0,
    ) -> None:
        _overrides: Dict[str, Any] = coalesce(overrides, {})
        settings_override = {
            "api_key": self.dst_api_key,
            "base_url": self.dst_base_url,
        }

        send_run_with_send_manager(
            run,
            rewind_steps=rewind_steps,  # Pass rewind_steps to send_run_with_send_manager
            overrides=_overrides,
            settings_override=settings_override,
        )

    def import_runs(
        self,
        runs: Iterable[WandbRun],
        overrides: Optional[Dict[str, Any]] = None,
        pool_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        _overrides: Dict[str, Any] = coalesce(overrides, {})
        _pool_kwargs: Dict[str, Any] = coalesce(pool_kwargs, {})
        runs = list(runs)

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
                        wandb.termerror(f"Import problem: {e}")
                    else:
                        pbar.set_postfix({"id": run.run.id})
                    finally:
                        pbar.update(1)

    def import_all_runs(
        self,
        entity: str,
        project: Optional[str] = None,
        limit: Optional[int] = None,
        overrides: Optional[Dict[str, Any]] = None,
        pool_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        runs = self.collect_runs(entity, project, limit)
        self.import_runs(runs, overrides, pool_kwargs)

    def collect_reports(
        self, entity: str, project: Optional[str] = None, limit: Optional[int] = None
    ) -> Generator[Report, None, None]:
        api = self.src_api
        projects = self._projects(entity, project)

        reports = (
            report
            for project in projects
            for report in api.reports(f"{project.entity}/{project.name}")
        )
        for i, report in enumerate(reports):
            if limit and i >= limit:
                break
            yield wr.Report.from_url(report.url, api=api)

    def import_report(
        self,
        report: Report,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        _overrides: Dict[str, Any] = coalesce(overrides, {})

        name = _overrides.get("name", report.name)
        entity = _overrides.get("entity", report.entity)
        project = _overrides.get("project", report.project)
        title = _overrides.get("title", report.title)
        description = _overrides.get("description", report.description)

        api = self.dst_api

        # Testing Hack: To support multithreading import_report
        # We shouldn't need to upsert the project for every report
        try:
            api.create_project(project, entity)
        except requests.exceptions.HTTPError as e:
            wandb.termwarn(f"{e} (Error 409 is probably safe)")

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

    def import_reports(
        self,
        reports: Iterable[Report],
        overrides: Optional[Dict[str, Any]] = None,
        pool_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        _overrides = coalesce(overrides, {})
        _pool_kwargs = coalesce(pool_kwargs, {})
        reports = list(reports)

        with ThreadPoolExecutor(**_pool_kwargs) as exc:
            futures = {
                exc.submit(self.import_report, report, overrides=_overrides): report
                for report in reports
            }
            with tqdm(
                desc="Importing reports", total=len(futures), unit="report"
            ) as pbar:
                for future in as_completed(futures):
                    _report = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        wandb.termerror(f"Import problem: {e}")
                    else:
                        pbar.set_postfix({"id": _report.id})
                    finally:
                        pbar.update(1)

    def import_all_reports(
        self,
        entity: str,
        project: Optional[str] = None,
        limit: Optional[int] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        reports = self.collect_reports(entity, project, limit)
        self.import_reports(reports, overrides)

    def rsync(
        self,
        entity: str,
        project: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        overrides = coalesce(overrides, {})

        # Actually there is a bug here.  If the project is deleted, the ids still appear to be here even though they are not!
        # dest_ent = overrides.get("entity", entity)
        # ids_in_dst = list(self._get_ids_in_dst(dest_ent))
        # wandb.termwarn(f"Found IDs already in destination.  Skipping {ids_in_dst}")
        # runs = self.download_all_runs_alt(entity, skip_ids=ids_in_dst)
        runs = self.collect_runs(entity, project, skip_ids=[])
        self.import_runs(runs, overrides)

        # do the same for reports?
        reports = self.collect_reports(entity)
        self.import_reports(reports, overrides)

    def rsync_time(
        self,
        entity: str,
        project: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> None:
        # instead of using ids, just use the last run timestamp
        from datetime import datetime as dt

        last_run_file = "_wandb_last_run.txt"
        last_run_time = None
        now = dt.now().isoformat()

        try:
            with open(last_run_file) as f:
                last_run_time = f.read()
        except FileNotFoundError:
            wandb.termlog("First time running importer.  Downloading everything...")
            last_run_time = "2016-01-01"
        else:
            wandb.termlog(f"Downloading runs created after {last_run_time}")

        runs = self.collect_runs(entity, project, start_date=last_run_time)
        self.import_runs(runs, overrides)

        with open(last_run_file, "w") as f:
            f.write(now)

    def _get_ids_in_dst(self, entity: str):
        api = self.dst_api
        for project in api.projects(entity):
            for run in api.runs(f"{project.entity}/{project.name}"):
                yield run.id

    def _projects(self, entity: str, project: Optional[str]):
        api = self.src_api
        if project is None:
            return api.projects(entity)
        return [api.project(project, entity)]


class WandbParquetRun(WandbRun):
    def metrics(self, rewind_steps: Optional[int] = 0) -> Iterable[Dict[str, float]]:
        self.history_paths = []
        for art in self.run.logged_artifacts():
            if art.type != "wandb-history":
                continue
            path = art.download()
            self.history_paths.append(path)

        if not self.history_paths:
            wandb.termwarn("No parquet files detected -- using scan_history")
            yield from super().metrics()
            return

        for path in self.history_paths:
            for p in Path(path).glob("*.parquet"):
                df = pl.read_parquet(p)

                # Rewind the specified number of steps
                df = df.head(len(df) - rewind_steps) if rewind_steps > 0 else df

                for row in df.iter_rows(named=True):
                    row = remove_keys_with_none_values(row)
                    yield row


class WandbParquetImporter(WandbImporter):
    DefaultRunClass = WandbParquetRun
