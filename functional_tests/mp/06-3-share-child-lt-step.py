#!/usr/bin/env python
"""Test parent and child processes sharing a run. Compare to a run in a single process.
example usage of `run.log` with user provide step less than the internal step"""

from contextlib import redirect_stderr
import io
import multiprocessing as mp

import wandb
import yea


def process_child(run):
    run.config.c2 = 22
    run.log({"s1": 210}, step=3, commit=True)


def process_parent():
    run = wandb.init()
    assert run == wandb.run
    run.log({"s1": 11})
    run.config.c1 = 11
    run.log({"s1": 4}, step=4, commit=False)


def share_run():
    process_parent()
    # Start a new run in parallel in a child process
    p = mp.Process(target=process_child, kwargs=dict(run=wandb.run))
    p.start()
    p.join()
    wandb.finish()


def refernce_run():
    process_parent()
    process_child(wandb.run)
    wandb.finish()


def main():
    wandb.require("service")

    refernce_run()

    share_run()


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
