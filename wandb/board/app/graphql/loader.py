data = {
    'Runs': []
}
from wandb import __stage_dir__
import glob
import os
import json


def load():
    global data

    from app.models import Dir, Description, Config, Summary, History, Events, Patch
    from .schema import Run
    base_path = __stage_dir__ or "/Users/vanpelt/Development/WandB/wandb-examples/simple/wandb"
    for path in sorted(glob.glob(base_path + "/*run-*"), key=lambda p: p.split("run-")[1], reverse=True):
        directory = Dir(path)
        desc = Description(path)
        config = Config(path)
        summary = Summary(path)
        patch = Patch(path)
        run = Run(
            path=path,
            id=directory.run_id,
            createdAt=directory.created_at,
            heartbeatAt=summary.updated_at,
            description=desc.read(),
            state="finished",
            patch=patch.read(),
            summaryMetrics=summary.parsed(),
            config=config.parsed()
        )
        data['Runs'].append(run)


def find_run(name):
    if name == "latest":
        return data["Runs"][0]
    else:
        return next(run for run in data["Runs"] if run.id == name)
