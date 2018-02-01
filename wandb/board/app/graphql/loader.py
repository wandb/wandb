from wandb import __stage_dir__
import glob
import os
import json
import re
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from wandb.board.app.models import Dir, Settings, RunMutator

base_path = __stage_dir__ or "/Users/vanpelt/Development/WandB/wandb-examples/simple/wandb"
data = {
    'Runs': []
}
settings = Settings(base_path)


def load():
    global data

    for path in sorted(glob.glob(base_path + "/*run-*"), key=lambda p: p.split("run-")[1], reverse=True):
        run_dir = Dir(path)
        data['Runs'].append(run_dir.load())
    watch_dir(base_path)


def watch_dir(path):
    def on_file_created(event):
        try:
            run_dir = Dir(event.src_path)
        except ValueError:
            return None
        if os.path.isdir(event.src_path):
            # TODO: ensure this is the top level dir?
            if run_dir.run_id and not find_run(run_dir.run_id):
                data["Runs"].insert(0, run_dir.load())
        run = find_run(run_dir.run_id)
        run_dir.load(run)

    def on_file_modified(event):
        try:
            run_dir = Dir(event.src_path)
        except ValueError:
            return None
        run = find_run(run_dir.run_id)
        run_dir.load(run)

    handler = PatternMatchingEventHandler(
        patterns=[os.path.join(path, "*")], ignore_patterns=['*/.*', '*.tmp'])
    handler.on_created = on_file_created
    handler.on_modified = on_file_modified
    observer = Observer()
    observer.schedule(handler, path, recursive=True)
    observer.start()


def find_run(name, mutator=False):
    if name == "latest":
        return data["Runs"][0]
    else:
        try:
            run = next(run for run in data["Runs"] if run.id == name)
        except StopIteration:
            run = None
        if mutator and run:
            return RunMutator(run)
        else:
            return run
