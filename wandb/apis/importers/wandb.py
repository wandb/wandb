import itertools
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import polars as pl
from tqdm import tqdm

import wandb
import wandb.apis.reports as wr
import os

from wandb.apis.importers.base import ImporterRun
from .base import Importer, ImporterRun
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from wandb.util import coalesce


class WandbRun(ImporterRun):
    def __init__(self, run, *args, **kwargs):
        self.run = run
        super().__init__(*args, **kwargs)

    def run_id(self):
        return self.run.id + "asdf"

    def entity(self):
        return self.run.entity

    def project(self):
        return self.run.project

    def config(self):
        return self.run.config

    def summary(self):
        return self.run.summary

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
        return self.run.created_at

    def runtime(self):
        return self.run.summary.get("_runtime")

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
        # this probably does not handle the case of runs linked together...
        from wandb.util import runid

        for art in self.run.used_artifacts():
            # name, ver = art.name.split(":")
            # art._client_id = runid.generate_id(128)
            # art._sequence_client_id = runid.generate_id(128)
            # art.distributed_id = None
            # art.incremental = False
            # art._name = name
            name, ver = art.name.split(":v")
            path = art.download()

            # Hack: skip naming validation check for wandb-* types
            new_art = wandb.Artifact(name, "temp")
            new_art._type = art.type

            new_art.add_dir(path)
            # wandb.termlog(f"{new_art.id}, {new_art.type}, {new_art.name}")

            yield new_art

            # yield art


class WandbImporter(Importer):
    def __init__(self, source_base_url, source_api_key, dest_base_url, dest_api_key):
        super().__init__()
        self.source_api = wandb.Api(
            api_key=source_api_key, overrides={"base_url": source_base_url}
        )
        self.dest_api = wandb.Api(
            api_key=dest_api_key, overrides={"base_url": dest_base_url}
        )
        self.runs = []

        self.source_base_url = source_base_url
        self.source_api_key = source_api_key
        self.dest_base_url = dest_base_url
        self.dest_api_key = dest_api_key

    def import_all_parallel(self, limit=None, pool_kwargs=None, overrides=None):
        runs = coalesce(runs, list(self.download_all_runs(limit=limit)))
        pool_kwargs = coalesce(pool_kwargs, {})
        overrides = coalesce(overrides, {})

        # consumer
        os.environ["WANDB_BASE_URL"] = self.dest_base_url
        os.environ["WANDB_API_KEY"] = self.dest_api_key

        with ThreadPoolExecutor(**pool_kwargs) as exc:
            futures = {
                exc.submit(self.import_one, run, overrides=overrides): run
                for run in runs
            }
            with tqdm(total=len(futures)) as pbar:
                for future in as_completed(futures):
                    runs = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        pass
                    finally:
                        pbar.update(1)

    def import_all(self, limit=None):
        # producer
        runs = coalesce(runs, self.download_all_runs(limit=limit))

        # consumer
        os.environ["WANDB_BASE_URL"] = self.dest_base_url
        os.environ["WANDB_API_KEY"] = self.dest_api_key

        for run in self.runs:
            wandb.termlog(
                f"Getting {run.entity()}/{run.project()}/{run.display_name()}"
            )
            self.import_one(run, overrides={"entity": "andrew"})

    def download_all_runs(self, limit=None) -> Iterable[ImporterRun]:
        for i, run in enumerate(self._download_all_runs()):
            if limit and i >= limit:
                break
            yield run

    def _download_all_runs(self) -> None:
        for project in self.source_api.projects():
            for run in self.source_api.runs(project.name):
                yield WandbRun(run)

    def download_all_reports(self, limit=None):
        for i, report in enumerate(self._download_all_reports()):
            if limit and i >= limit:
                break
            yield report

    def _download_all_reports(self) -> None:
        projects = [p for p in self.source_api.projects()]
        with tqdm(projects, "Collecting reports...") as projects:
            for project in projects:
                for report in self.source_api.reports(project.name):
                    try:
                        r = wr.Report.from_url(report.url)
                    except Exception as e:
                        pass
                    else:
                        yield r

    def import_all_reports_parallel(
        self,
        reports: Optional[Iterable[wr.Report]] = None,
        pool_kwargs: Optional[Dict[str, Any]] = None,
        overrides: Optional[Dict[str, Any]] = None,
        limit=None,
    ) -> None:
        reports = coalesce(reports, list(self.download_all_reports(limit=limit)))
        pool_kwargs = coalesce(pool_kwargs, {})

        with ThreadPoolExecutor(**pool_kwargs) as exc:
            futures = {
                exc.submit(self.import_one_report, report, overrides=overrides): report
                for report in reports
            }
            with tqdm(total=len(futures)) as pbar:
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
        project = overrides.get("entity", report.project)
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


class WandbParquetRun(WandbRun):
    def metrics(self):
        arts = list(self.run.logged_artifacts())
        # wandb.termlog(f"{self.entity()}/{self.project()}/{self.display_name()}")
        # wandb.termlog(f"{arts=}")
        art = None
        for art in arts:
            if art.type == "wandb-history":
                break
        if art.type != "wandb-history":
            raise Exception("No parquet file!")

        path = art.download()
        dfs = (pl.read_parquet(p) for p in Path(path).glob("*.parquet"))
        rows = (df.iter_rows(named=True) for df in dfs)
        return itertools.chain(*rows)


class WandbParquetImporter(WandbImporter):
    def _download_all_runs(self):
        for project in self.source_api.projects():
            for run in self.source_api.runs(project.name):
                yield WandbParquetRun(run)
