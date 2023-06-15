import itertools
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime as dt
from functools import partial
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import patch

import polars as pl
import yaml
from tqdm.auto import tqdm

import wandb
from wandb.util import coalesce

from .base import Importer, ImporterRun

with patch("click.echo"):
    import wandb.apis.reports as wr


class WandbRun(ImporterRun):
    def __init__(self, run, *args, **kwargs):
        self.run = run
        super().__init__(*args, **kwargs)

        # download everything up front before switching api keys
        with patch("click.echo"):
            self._files = self.files()
            self._artifacts = self.artifacts()
            self._used_artifacts = self.used_artifacts()
            self._logs = self.logs()

            self._files = list(self._files)
            self._artifacts = list(self._artifacts)
            self._used_artifacts = list(self._used_artifacts)
            self._logs = list(self._logs)

    def host(self):
        fname = None
        for name, _ in self._files:
            if "wandb-metadata.json" in name:
                fname = name
                break

        if fname is None:
            return None

        with open(fname) as f:
            result = json.loads(f.read())

        return result.get("host")

    def logs(self):
        fname = None
        for name, _ in self._files:
            if "output.log" in name:
                fname = name
                break

        if fname is None:
            return None

        with open(fname) as f:
            yield from f.readlines()

    def code_path(self):
        fname = None
        for name, _ in self._files:
            if "wandb-metadata.json" in name:
                fname = name
                break

        if fname is None:
            return None

        with open(fname) as f:
            result = json.loads(f.read())

        return "code/" + result.get("codePath", "")

    def cli_version(self):
        fname = None
        for name, _ in self._files:
            if "config.yaml" in name:
                fname = name
                break

        if fname is None:
            return None

        with open(fname) as f:
            result = yaml.safe_load(f)

        return result.get("_wandb", {}).get("value", {}).get("cli_version")

    def python_version(self):
        fname = None
        for name, _ in self._files:
            if "wandb-metadata.json" in name:
                fname = name
                break

        if fname is None:
            return None

        with open(fname) as f:
            result = json.loads(f.read())

        return result.get("python")

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
        for art in self.run.logged_artifacts():
            name, ver = art.name.split(":v")
            path = art.download()

            # Hack: skip naming validation check for wandb-* types
            new_art = wandb.Artifact(name, "temp")
            new_art._type = art.type

            new_art.add_dir(path)

            yield new_art

    def used_artifacts(self):
        for art in self.run.used_artifacts():
            name, ver = art.name.split(":v")
            path = art.download()

            # Hack: skip naming validation check for wandb-* types
            new_art = wandb.Artifact(name, "temp")
            new_art._type = art.type

            new_art.add_dir(path)

            yield new_art

    def files(self):
        base_path = f"{self.run_dir}/files"
        for f in self.run.files():
            result = f.download(base_path, exist_ok=True)
            yield (result.name, "now")

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

            # Try to pick up the artifact within 30 seconds
            for _ in range(15):
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


class WandbImporter(Importer):
    def __init__(
        self,
        source_base_url: str,
        source_api_key: str,
        dest_base_url: str,
        dest_api_key: str,
        overrides=None,
    ):
        super().__init__()
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

        self.src_env = partial(env, source_api_key, source_base_url)
        self.dst_env = partial(env, dest_api_key, dest_base_url)
        self.overrides = overrides

    def import_one_run(
        self,
        run: WandbRun,
        overrides: Optional[Dict[str, Any]] = None,
    ):
        # consumer
        os.environ["WANDB_BASE_URL"] = self.dest_base_url
        os.environ["WANDB_API_KEY"] = self.dest_api_key
        super().import_one_run(run, overrides)

    def import_all_runs(
        self,
        runs: Optional[Iterable[WandbRun]] = None,
        entity: Optional[str] = None,
        limit: Optional[int] = None,
        pool_kwargs: Optional[Dict[str, Any]] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ):
        pool_kwargs = coalesce(pool_kwargs, {})
        overrides = coalesce(overrides, {})

        if runs is None:
            runs = list(self.download_all_runs(entity, limit))

        with ThreadPoolExecutor(**pool_kwargs) as exc:
            futures = {
                exc.submit(self.import_one_run, run, overrides=overrides): run
                for run in runs
            }
            with tqdm(desc="Importing runs", total=len(futures)) as pbar:
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        wandb.termerror(f"Import problem: {e}")
                        raise e
                    finally:
                        pbar.update(1)

    def rsync(self, entity):
        ids_in_dst = list(self._get_ids_in_dst(entity))
        runs = self.download_all_runs(skip_ids=ids_in_dst)
        self.import_all_runs(runs)

    def _get_ids_in_dst(self, entity):
        for project in self.source_api.projects(entity):
            for run in self.source_api.runs(f"{project.entity}/{project.name}"):
                yield run.id

    def download_all_runs(
        self,
        entity: Optional[str] = None,
        limit: Optional[int] = None,
        skip_ids: Optional[List[str]] = None,
        created_after: Optional[str] = None,
    ) -> Iterable[ImporterRun]:
        filters = {}
        if skip_ids:
            filters["name"] = {"$nin": skip_ids}
        if created_after:
            filters["createdAt"] = {"$gte": dt.fromisoformat(created_after)}

        runs = self._download_all_runs(entity, filters)
        empty, runs = generator_is_empty(runs)

        if empty:
            wandb.termwarn("No importable runs found!")
            return

        for i, run in tqdm(enumerate(runs), "Collecting runs (this may take a while)", total=limit):
            if limit and i >= limit:
                break
            yield run

    def _download_all_runs(
        self, entity: str, filters: Optional[Dict[str, Any]] = None
    ) -> None:
        for project in self.source_api.projects(entity):
            for run in self.source_api.runs(
                f"{project.entity}/{project.name}", filters
            ):
                yield WandbRun(run)

    def download_all_reports(self, limit: Optional[int] = None):
        for i, report in tqdm(
            enumerate(self._download_all_reports()),
            "Collecting reports",
            total=limit,
        ):
            if limit and i >= limit:
                break
            yield report

    def _download_all_reports(self) -> None:
        for project in self.source_api.projects():
            for report in self.source_api.reports(f"{project.entity}/{project.name}"):
                try:
                    r = wr.Report.from_url(report.url)
                except Exception as e:
                    pass
                else:
                    # projects.set_postfix(
                    #     {
                    #         "Project": r.project,
                    #         "Report": r.title,
                    #         "ID": r.id,
                    #     }
                    # )
                    yield r

    def import_all_reports(
        self,
        reports: Optional[Iterable[wr.Report]] = None,
        pool_kwargs: Optional[Dict[str, Any]] = None,
        overrides: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> None:
        reports = coalesce(reports, list(self.download_all_reports(limit=limit)))
        pool_kwargs = coalesce(pool_kwargs, {})

        with ThreadPoolExecutor(**pool_kwargs) as exc:
            futures = {
                exc.submit(self.import_one_report, report, overrides=overrides): report
                for report in reports
            }
            with tqdm(desc="Importing reports", total=len(futures)) as pbar:
                for future in as_completed(futures):
                    report = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        wandb.termerror(
                            f"Failed to import {report.title} {report.id}: {exc}"
                        )
                        with open("failed.txt", "a") as f:
                            f.write(f"{report.id}\n")
                    else:
                        pbar.set_postfix(
                            {
                                "Project": report.project,
                                "Report": report.title,
                                "ID": report.id,
                            }
                        )
                        with open("success.txt", "a") as f:
                            f.write(f"{report.id}\n")
                    finally:
                        pbar.update(1)

    def import_one_report(
        self, report: wr.Report, overrides: Optional[Dict[str, Any]] = None
    ):
        overrides = coalesce(overrides, {})
        name = overrides.get("name", report.name)
        entity = overrides.get("entity", report.entity)
        project = overrides.get("project", report.project)
        title = overrides.get("title", report.title)
        description = overrides.get("description", report.description)

        self.dest_api.create_project(project, entity)

        # hack to skip the default save path which can be very slow
        # ID will not match the originating server's ID.  if you import twice,
        # You will end up with two of the same report (with different IDs).
        self.dest_api.client.execute(
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

    def _make_metadata_file(self, run_dir: str) -> None:
        # skip because we have our own metadata already
        pass


class WandbParquetRun(WandbRun):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.history_arts = [
            art for art in self.run.logged_artifacts() if art.type == "wandb-history"
        ]

        # download up here because the env var is still set to be source... kinda hacky
        with patch("click.echo"):
            self.history_paths = [art.download() for art in self.history_arts]

        self.api = wandb.Api(
            api_key="ed3b84bc5bc8bd5877f11f79ab8a8124cf41cf50",
            overrides={"base_url": "https://api.wandb.test"},
        )

        # I think there is an edge case with multiple wandb-history artifacts.
        if len(self.history_arts) == 0:
            wandb.termwarn("No parquet files detected!")

    def metrics(self):
        for path in self.history_paths:
            for p in Path(path).glob("*.parquet"):
                df = pl.read_parquet(p)
                for row in df.iter_rows(named=True):
                    row = remove_none_values(row)
                    yield row


class WandbParquetImporter(WandbImporter):
    def _download_all_runs(
        self, entity: str, filters: Optional[Dict[str, Any]] = None
    ) -> None:
        for project in self.source_api.projects(entity):
            for run in self.source_api.runs(
                f"{project.entity}/{project.name}", filters
            ):
                yield WandbParquetRun(run)


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


def generator_is_empty(gen):
    try:
        first = next(gen)
    except StopIteration:  # generator was empty, return an empty generator
        return True, gen
    else:  # generator has elements, return a new generator with the first element re-attached
        return False, itertools.chain([first], gen)


@contextmanager
def env(api_key, base_url):
    starting_api_key = os.getenv("WANDB_API_KEY", "")
    starting_base_url = os.getenv("WANDB_BASE_URL", "")

    os.environ["WANDB_API_KEY"] = api_key
    os.environ["WANDB_BASE_URL"] = base_url

    yield

    os.environ["WANDB_API_KEY"] = starting_api_key
    os.environ["WANDB_BASE_URL"] = starting_base_url
