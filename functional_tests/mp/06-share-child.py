#!/usr/bin/env python
"""Test parent and child processes sharing a run."""

from contextlib import redirect_stderr
import io
import multiprocessing as mp

import wandb
import yea


def process_child(run):
    run.config.c2 = 22
    run.log({"s1": 21})
    f = io.StringIO()
    with redirect_stderr(f):
        run.log({"s1": 210}, step=12, commit=True)
        assert (
            "Step cannot be set when using run in multiple processes. Please log your step values as a metric such as 'global_step'"
            in f.getvalue()
        )


def main():
    wandb.require("service")

    run = wandb.init()
    run.config.c1 = 11
    run.log({"s1": 11})
    run.log({"s2": 12})
    run.log({"s2": 120})

    # Start a new run in parallel in a child process
    p = mp.Process(target=process_child, kwargs=dict(run=run))
    p.start()
    p.join()

    run.log({"s3": 13})
    run.log({"s3": 4}, step=4, commit=True)

    run.log({"s1": 120}, step=100)


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
