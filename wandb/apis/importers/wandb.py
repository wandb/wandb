import wandb
import polars as pl
from pathlib import Path
import itertools
from .base import Importer, ImporterRun


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
        ...


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


class WandbParquetRun(WandbRun):
    def metrics(self):
        return get_history_rows(self.run)


class WandbParquetImporter(WandbImporter):
    def download_all_runs(self):
        for run in self.api.runs("parquet-testing"):
            yield WandbParquetRun(run)


def get_history_rows(run):
    for art in run.logged_artifacts():
        if art.type == "wandb-history":
            break
    path = art.download()
    dfs = [pl.read_parquet(p) for p in Path(path).glob("*.parquet")]
    rows = [df.iter_rows(named=True) for df in dfs]
    return itertools.chain(*rows)
