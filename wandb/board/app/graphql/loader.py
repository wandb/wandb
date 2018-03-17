from wandb import wandb_dir
import glob
import os
import json
import re
import logging
import sys
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from wandb.board.app.models import Dir, Settings, RunMutator
from wandb.board.app.util.errors import NotFoundError
from wandb import Error

base_path = wandb_dir()
data = {
    'Runs': []
}
settings = Settings(base_path)


def load(path_override=None):
    global data
    data['Runs'] = []
    root = os.path.abspath(path_override or base_path)
    if os.path.exists(root):
        print("Loading %s ..." % root)
    else:
        raise Error("Directory does not exist: %s" % root)
    settings.path = root
    for path in sorted(glob.glob(root + "/*run-*"), key=lambda p: p.split("run-")[1], reverse=True):
        run_dir = Dir(path)
        data['Runs'].append(run_dir.load())
    watch_dir(root)


def watch_dir(path):
    def on_file_created(event):
        try:
            run_dir = Dir(event.src_path)
        except ValueError:
            return None
        if os.path.isdir(event.src_path):
            # TODO: ensure this is the top level dir?
            if run_dir.run_id and not find_run(run_dir.run_id):
                print("New run started at %s" % run_dir.path)
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
        elif run is None:
            raise NotFoundError("Run %s not found" % name)
        else:
            return run
