import itertools
from contextlib import contextmanager
from pathlib import Path

import polars as pl
from tqdm import tqdm

import wandb
import wandb.apis.reports as wr
from wandb.sdk.lib import runid
import os
from .base import Importer, ImporterRun
from concurrent.futures import ThreadPoolExecutor, as_completed

old_api_key = os.getenv("WANDB_API_KEY")
new_api_key = os.getenv("WANDB_API_KEY2")


class WandbRun(ImporterRun):
    def __init__(self, run):
        self.run = run
        super().__init__()

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
        # return [next(self.run.scan_history())]

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
        return self.run.summary["_runtime"]

    def artifacts(self):
        for art in self.run.logged_artifacts():
            if art.type == "wandb-history":
                continue

            # Is this safe?
            art._client_id = runid.generate_id(128)
            art._sequence_client_id = runid.generate_id(128)
            art.distributed_id = None
            art.incremental = False

            name, ver = art.name.split(":v")
            art._name = name

            yield art
        # return [
        #     art for art in self.run.logged_artifacts() if art.type != "wandb-history"
        # ]


class WandbImporter(Importer):
    def __init__(self, wandb_source=None, wandb_target=None):
        super().__init__()
        self.api = wandb.Api()
        self.wandb_source = wandb_source
        self.wandb_target = wandb_target

    def download_all_runs(self):
        # for project in api.projects():
        #     for run in api.runs(project.name):
        #         yield WandbRun(run)

        for run in self.api.runs("parquet-testing"):
            yield WandbRun(run)

    def download_all_reports(self):
        # for p in self.api.projects():
        #     for r in self.api.reports(p.name):
        #         try:
        #             yield wr.Report.from_url(r.url)
        #         except Exception as e:
        #             print(e)
        with tqdm(
            [p for p in self.api.projects()], "Collecting reports..."
        ) as projects:
            for p in projects:
                with tqdm(
                    [r for r in self.api.reports(p.name)], "Subtask", leave=False
                ) as reports:
                    for _report in reports:
                        try:
                            report = wr.Report.from_url(_report.url)
                        except Exception as e:
                            wandb.termerror(str(e))
                            wandb.termerror(
                                f"project: {p.name}, report_id: {_report.id}"
                            )
                            with open("failed.txt", "a") as f:
                                f.write(f"{report.id}\n")
                        # projects.set_postfix(
                        #     {"Project": p.name, "Report": report.title, "ID": report.id}
                        # )
                        yield report

    def import_all_reports_parallel(self, reports=None, overrides=None, **pool_kwargs):
        if reports is None:
            reports = list(self.download_all_reports())

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

    def import_one_report(self, report, overrides=None):
        with login_wrapper(old_api_key, new_api_key):
            report2 = wr.Report(
                entity="andrewtruong",
                project=report.project,
                description=report.description,
                width=report.width,
                blocks=report.blocks,
            )
            report2.save()


class WandbParquetRun(WandbRun):
    def metrics(self):
        for art in self.run.logged_artifacts():
            if art.type == "wandb-history":
                break
        path = art.download()
        dfs = [pl.read_parquet(p) for p in Path(path).glob("*.parquet")]
        rows = [df.iter_rows(named=True) for df in dfs]
        return itertools.chain(*rows)


class WandbParquetImporter(WandbImporter):
    def download_all_runs(self):
        for run in self.api.runs("parquet-testing"):
            yield WandbParquetRun(run)


@contextmanager
def login_wrapper(old_api_key, new_api_key):
    """
    A very sketchy function
    """
    # wandb.login(key=new_api_key)
    wandb.api.api._environ["WANDB_API_KEY"] = new_api_key
    try:
        yield
    except Exception as e:
        raise e
    finally:
        # wandb.login(key=old_api_key)
        wandb.api.api._environ["WANDB_API_KEY"] = old_api_key
