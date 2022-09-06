#!/usr/bin/env python
"""Test parent and child processes sharing a run. Compare to a run in a single process.
example usage of `run.log` with user provide step less than the internal step"""

import io
import multiprocessing as mp
from contextlib import redirect_stderr

import wandb
import yea


def process_child(run, check_warning=False):
    run.config.c2 = 22

    f = io.StringIO()
    with redirect_stderr(f):
        run.log({"s1": 210}, step=3, commit=True)

        found_warning = (
            "Note that setting step in multiprocessing can result in data loss. Please log your step values as a metric such as 'global_step'"
            in f.getvalue()
        )
        assert found_warning if check_warning else not found_warning


def process_parent():
    run = wandb.init()
    assert run == wandb.run
    run.log({"s1": 11})
    run.config.c1 = 11
    run.log({"s1": 4}, step=4, commit=False)


def share_run():
    process_parent()
    # Start a new run in parallel in a child process
    p = mp.Process(target=process_child, kwargs=dict(run=wandb.run, check_warning=True))
    p.start()
    p.join()
    wandb.finish()


def reference_run():
    process_parent()
    process_child(wandb.run)
    wandb.finish()


def main():
    wandb.require("service")

    reference_run()

    share_run()


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
