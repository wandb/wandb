import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime as dt
from pathlib import Path
from unittest.mock import patch

import polars as pl
import yaml
from tqdm.auto import tqdm

import wandb
from wandb.util import coalesce

from .base import (
    Importer,
    ImporterRun,
    _thread_local_settings,
    set_thread_local_settings,
)

with patch("click.echo"):
    import wandb.apis.reports as wr


class WandbRun(ImporterRun):
    def __init__(self, run, *args, **kwargs):
        self.run = run
        super().__init__(*args, **kwargs)

        self.api = wandb.Api(
            api_key=_thread_local_settings.api_key,
            overrides={"base_url": _thread_local_settings.base_url},
        )

        # download everything up front before switching api keys
        # with patch("click.echo"):
        self._files = self.files()
        self._artifacts = self.artifacts()
        self._used_artifacts = self.used_artifacts()
        self._logs = self.logs()

        self._files = list(self._files)
        self._artifacts = list(self._artifacts)
        self._used_artifacts = list(self._used_artifacts)
        self._logs = list(self._logs)

    def run_id(self):
        return self.run.id

    def entity(self):
        return self.run.entity

    def project(self):
        return self.run.project

    def config(self):
        return self.run.config

    def summary(self):
        s = self.run.summary

        # Hack: We need to overwrite the artifact path for logged tables because
        # they are different between systems!
        s = self._modify_table_artifact_paths(s)
        return s

    def metrics(self):
        return self.run.scan_history()

    def run_group(self):
        return self.run.group

    def job_type(self):
        return self.run.job_type

    def display_name(self):
        return self.run.display_name

    def notes(self):
        return self.run.notes

    def tags(self):
        return self.run.tags

    def start_time(self):
        t = dt.fromisoformat(self.run.created_at).timestamp()
        return int(t)

    def runtime(self):
        wandb_runtime = self.run.summary.get("_wandb", {}).get("runtime")
        base_runtime = self.run.summary.get("_runtime")

        t = coalesce(wandb_runtime, base_runtime)
        if t is None:
            return t
        return int(t)

    def artifacts(self):
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

    def used_artifacts(self):
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

    def files(self):
        base_path = f"{self.run_dir}/files"
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

    def host(self):
        fname = self._find_in_files("wandb-metadata.json")
        if fname is None:
            return

        with open(fname) as f:
            result = json.loads(f.read())
            return result.get("host")

    def logs(self):
        fname = self._find_in_files("output.log")
        if fname is None:
            return

        with open(fname) as f:
            yield from f.readlines()

    def code_path(self):
        fname = self._find_in_files("wandb-metadata.json")
        if fname is None:
            return

        with open(fname) as f:
            result = json.loads(f.read())
            return "code/" + result.get("codePath", "")

    def cli_version(self):
        fname = self._find_in_files("config.yaml")
        if fname is None:
            return

        with open(fname) as f:
            result = yaml.safe_load(f)
            return result.get("_wandb", {}).get("value", {}).get("cli_version")

    def python_version(self):
        fname = self._find_in_files("wandb-metadata.json")
        if fname is None:
            return

        with open(fname) as f:
            result = json.loads(f.read())
            return result.get("python")

    def _modify_table_artifact_paths(self, row):
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

    def _find_in_files(self, name):
        for path, _ in self._files:
            if name in path:
                return path


class WandbImporter(Importer):
    DefaultRunClass = WandbRun

    def __init__(
        self,
        source_base_url: str,
        source_api_key: str,
        dest_base_url: str,
        dest_api_key: str,
    ):
        super().__init__()

        # There is probably a less redundant way of doing this
        self.source_api = wandb.Api(
            api_key=source_api_key,
            overrides={"base_url": source_base_url},
        )
        self.dest_api = wandb.Api(
            api_key=dest_api_key,
            overrides={"base_url": dest_base_url},
        )
        self.source_base_url = source_base_url
        self.source_api_key = source_api_key
        self.dest_base_url = dest_base_url
        self.dest_api_key = dest_api_key

    def collect_runs(
        self, entity, project=None, limit=None, skip_ids=None, start_date=None
    ):
        filters = {}
        if skip_ids is not None:
            filters["name"] = {"$nin": skip_ids}
        if start_date is not None:
            filters["createdAt"] = {"$gte": start_date}

        api = self.source_api
        projects = self._projects(entity, project)

        runs = (
            run
            for project in projects
            for run in api.runs(f"{project.entity}/{project.name}", filters=filters)
        )
        for i, run in enumerate(runs):
            if limit and i >= limit:
                break
            yield run

    def import_run(self, entity, project, id, overrides=None):
        if overrides is None:
            overrides = {}

        # wandb.termlog("GETTING SOURCE RUN")
        api = self.source_api
        run = api.run(f"{entity}/{project}/{id}")

        # set threadlocal here?
        set_thread_local_settings(self.dest_api_key, self.dest_base_url)
        run = self.DefaultRunClass(run)

        # wandb.termlog("UPLOADING TO DEST")
        super().import_run(
            run,
            overrides=overrides,
            settings_override={
                "api_key": self.dest_api_key,
                "base_url": self.dest_base_url,
            },
        )

    def import_runs(self, runs, overrides=None, pool_kwargs=None):
        overrides = coalesce(overrides, {})
        pool_kwargs = coalesce(pool_kwargs, {})
        runs = list(runs)
        with ThreadPoolExecutor(**pool_kwargs) as exc:
            futures = {
                exc.submit(
                    self.import_run,
                    run.entity,
                    run.project,
                    run.id,
                    overrides=overrides,
                ): run
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
                        pbar.set_postfix({"id": run.id})
                    finally:
                        pbar.update(1)

    def import_all_runs(self, entity, project=None, limit=None, overrides=None):
        runs = self.collect_runs(entity, project, limit)
        self.import_runs(runs, overrides)

    def collect_reports(self, entity, project=None, limit=None):
        api = self.source_api
        projects = self._projects(entity, project)

        reports = (
            report
            for project in projects
            for report in api.reports(f"{project.entity}/{project.name}")
        )
        for i, report in enumerate(reports):
            if limit and i >= limit:
                break
            yield report

    def import_report(self, report_url, overrides=None):
        overrides = coalesce(overrides, {})

        report = wr.Report.from_url(report_url)
        name = overrides.get("name", report.name)
        entity = overrides.get("entity", report.entity)
        project = overrides.get("project", report.project)
        title = overrides.get("title", report.title)
        description = overrides.get("description", report.description)

        api = self.dest_api

        api.create_project(project, entity)

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

    def import_reports(self, reports, overrides=None, pool_kwargs=None):
        overrides = coalesce(overrides, {})
        pool_kwargs = coalesce(pool_kwargs, {})
        reports = list(reports)

        with ThreadPoolExecutor(**pool_kwargs) as exc:
            futures = {
                exc.submit(self.import_report, report.url, overrides=overrides): report
                for report in reports
            }
            with tqdm(
                desc="Importing reports", total=len(futures), unit="report"
            ) as pbar:
                for future in as_completed(futures):
                    report = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        wandb.termerror(f"Import problem: {e}")
                    else:
                        pbar.set_postfix({"id": report.id})
                    finally:
                        pbar.update(1)

    def import_all_reports(self, entity, project=None, limit=None, overrides=None):
        reports = self.collect_reports(entity, project, limit)
        self.import_reports(reports, overrides)

    def rsync(self, entity, project=None, overrides=None):
        overrides = coalesce(overrides, {})

        # Actually there is a bug here.  If the project is deleted, the ids still appear to be here even though they are not!
        # dest_ent = overrides.get("entity", entity)
        # ids_in_dst = list(self._get_ids_in_dst(dest_ent))
        # wandb.termwarn(f"Found IDs already in destination.  Skipping {ids_in_dst}")
        # runs = self.download_all_runs_alt(entity, skip_ids=ids_in_dst)
        runs = self.collect_runs(entity, skip_ids=[])
        self.import_runs(runs, overrides)

        # do the same for reports?
        reports = self.collect_reports(entity)
        self.import_reports(reports, overrides)

    def rsync_time(self, entity, project=None, overrides=None):
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

        runs = self.collect_runs(entity, start_date=last_run_time)
        self.import_runs(runs, overrides)

        with open(last_run_file, "w") as f:
            f.write(now)

    def _get_ids_in_dst(self, entity):
        api = self.dest_api
        for project in api.projects(entity):
            for run in api.runs(f"{project.entity}/{project.name}"):
                yield run.id

    def _make_metadata_file(self, run_dir: str) -> None:
        # skip because we have our own metadata already
        pass

    def _projects(self, entity, project):
        api = self.source_api
        if project is None:
            projects = api.projects(entity)
        else:
            projects = [api.project(project, entity)]

        return projects


class WandbParquetRun(WandbRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # download up here because the env var is still set to be source... kinda hacky
        with patch("click.echo"):
            self.history_paths = []
            for art in self.run.logged_artifacts():
                if art.type != "wandb-history":
                    continue
                path = art.download()
                self.history_paths.append(path)

        if len(self.history_paths) == 0:
            wandb.termwarn("No parquet files detected!")

    def metrics(self):
        for path in self.history_paths:
            for p in Path(path).glob("*.parquet"):
                df = pl.read_parquet(p)
                for row in df.iter_rows(named=True):
                    row = remove_none_values(row)
                    yield row


class WandbParquetImporter(WandbImporter):
    DefaultRunClass = WandbParquetRun


def remove_none_values(d):
    # otherwise iterrows will create a bunch of ugly charts
    if isinstance(d, dict):
        new_dict = {}
        for k, v in d.items():
            new_v = remove_none_values(v)
            if new_v is not None and not (isinstance(new_v, dict) and len(new_v) == 0):
                new_dict[k] = new_v
        return new_dict if new_dict else None
    return d
