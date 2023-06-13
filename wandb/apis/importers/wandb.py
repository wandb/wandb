from pathlib import Path
from typing import Any, Dict, Iterable, Optional


import polars as pl
from tqdm.auto import tqdm
import wandb
import wandb.apis.reports as wr
import os

from wandb.util import coalesce
from wandb.apis.importers.base import ImporterRun
from .base import Importer, ImporterRun
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from datetime import datetime as dt


class WandbRun(ImporterRun):
    def __init__(self, run, *args, **kwargs):
        self.run = run
        super().__init__(*args, **kwargs)

        # download everything up front before switching api keys
        self._files = list(self.files())
        self._artifacts = list(self.artifacts())
        self._used_artifacts = list(self.used_artifacts())

    def run_id(self):
        return self.run.id

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
            yield (result.name, "end")


class WandbImporter(Importer):
    def __init__(
        self,
        source_base_url: str,
        source_api_key: str,
        dest_base_url: str,
        dest_api_key: str,
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

    def import_all_parallel(
        self,
        # runs: Optional[Iterable[WandbRun]] = None,
        entity: Optional[str] = None,
        limit: Optional[int] = None,
        success_path="success.txt",
        failure_path="failure.txt",
        last_imported_path="last_imported.txt",
        pool_kwargs: Optional[Dict[str, Any]] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ):
        # if runs is None:
        #     runs = list(
        #         self.download_all_runs(
        #             entity=entity,
        #             limit=limit,
        #             success_path=success_path,
        #             last_imported_path=last_imported_path,
        #         )
        #     )
        runs = list(
            self.download_all_runs(entity, limit, success_path, last_imported_path)
        )

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
                    run = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        wandb.termerror(f"Import problem: {e}")
                        with open(failure_path, "a") as f:
                            f.write(f"{run.run_id()}\n")
                        raise e
                    else:
                        with open(success_path, "a") as f:
                            f.write(f"{run.run_id()}\n")
                    finally:
                        pbar.update(1)

    # def import_all(
    #     self,
    #     runs: Optional[Iterable[WandbRun]] = None,
    #     limit: Optional[int] = None,
    #     success_path="success.txt",
    #     failure_path="failure.txt",
    #     last_imported_path="last_imported.txt",
    # ):
    #     # producer
    #     if runs is None:
    #         runs = self.download_all_runs(
    #             limit=limit,
    #             success_path=success_path,
    #             last_imported_path=last_imported_path,
    #         )

    #     # consumer
    #     os.environ["WANDB_BASE_URL"] = self.dest_base_url
    #     os.environ["WANDB_API_KEY"] = self.dest_api_key

    #     for run in runs:
    #         wandb.termlog(
    #             f"Getting {run.entity()}/{run.project()}/{run.display_name()}"
    #         )
    #         try:
    #             self.import_one(run, overrides={"entity": "andrew"})
    #         except Exception as e:
    #             wandb.termerror(f"Import problem: {e}")
    #             with open(failure_path, "a") as f:
    #                 f.write(f"{run.run_id()}\n")
    #         else:
    #             with open(success_path, "a") as f:
    #                 f.write(f"{run.run_id()}\n")

    def download_all_runs(
        self,
        entity: Optional[str] = None,
        limit: Optional[int] = None,
        success_path="success.txt",
        last_imported_path="last_imported.txt",
    ) -> Iterable[ImporterRun]:
        already_imported = set()
        if os.path.isfile(success_path):
            with open(success_path) as f:
                already_imported = set(f.readlines())

        last_checked_time = dt.fromisoformat("2016-01-01").isoformat()
        now = dt.utcnow().isoformat()
        if os.path.exists(last_imported_path):
            with open(last_imported_path) as f:
                last_checked_time = f.readline()

        wandb.termlog(f"The last checked time was {last_checked_time}")

        i, run = None, None
        for i, run in enumerate(
            self._download_all_runs(entity, already_imported, last_checked_time)
        ):
            if limit and i >= limit:
                break
            yield run

        if i is None and run is None:
            wandb.termwarn("No importable runs found!!")

        with open(last_imported_path, "w") as f:
            f.write(now)

    def _download_all_runs(
        self, entity: str, already_imported: list, last_checked_time: str
    ) -> None:
        for project in self.source_api.projects(entity):
            for run in self.source_api.runs(
                f"{project.entity}/{project.name}",
                filters={
                    "createdAt": {"$gte": last_checked_time},
                    "name": {"$nin": already_imported},
                },
            ):
                yield WandbRun(run)

    def download_all_reports(self, limit: Optional[int] = None):
        for i, report in enumerate(self._download_all_reports()):
            if limit and i >= limit:
                break
            yield report

    def _download_all_reports(self) -> None:
        projects = [p for p in self.source_api.projects()]
        with tqdm(projects, "Collecting reports...") as projects:
            for project in projects:
                for report in self.source_api.reports(
                    f"{project.entity}/{project.name}"
                ):
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
        limit: Optional[int] = None,
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.history_arts = [
            art for art in self.run.logged_artifacts() if art.type == "wandb-history"
        ]

        # download up here because the env var is still set to be source... kinda hacky
        self.history_paths = [art.download() for art in self.history_arts]

        # I think there is an edge case with multiple wandb-history artifacts.
        if len(self.history_arts) == 0:
            wandb.termwarn("No parquet files detected!")

    def metrics(self):
        for path in self.history_paths:
            for p in Path(path).glob("*.parquet"):
                df = pl.read_parquet(p)

                # images, videos, etc will be packed as structs and not render properly
                non_structs = [
                    col
                    for col, dtype in zip(df.columns, df.dtypes)
                    if not isinstance(dtype, pl.Struct)
                ]
                df2 = df.select(non_structs)

                for row in df.iter_rows(named=True):
                    yield row


class WandbParquetImporter(WandbImporter):
    def _download_all_runs(
        self, entity: str, already_imported: list, last_checked_time: str
    ) -> None:
        for project in self.source_api.projects(entity):
            for run in self.source_api.runs(
                f"{project.entity}/{project.name}",
                filters={"createdAt": {"$gte": last_checked_time}},
            ):
                if run.id not in already_imported:
                    yield WandbParquetRun(run)
