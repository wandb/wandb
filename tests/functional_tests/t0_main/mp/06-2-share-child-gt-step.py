#!/usr/bin/env python
"""Test parent and child processes sharing a run. Compare to a run in a single process.
example usage of `run.log` with user provide step greater than the internal step"""


import io
import multiprocessing as mp
from contextlib import redirect_stderr

import wandb
import yea


def process_child(run, check_warning=False):
    run.config.c2 = 22

    f = io.StringIO()
    with redirect_stderr(f):
        run.log({"s1": 210}, step=12, commit=True)

        found_warning = (
            "Note that setting step in multiprocessing can result in data loss. Please log your step values as a metric such as 'global_step'"
            in f.getvalue()
        )
        assert found_warning if check_warning else not found_warning
    print(f.getvalue())


def process_parent(run):
    assert run == wandb.run
    run.config.c1 = 11
    run.log({"s1": 11})


def share_run():
    with wandb.init() as run:
        process_parent(run)
        # Start a new run in parallel in a child process
        p = mp.Process(target=process_child, kwargs=dict(run=run, check_warning=True))
        p.start()
        p.join()


def reference_run():
    with wandb.init() as run:
        process_parent(run)
        process_child(run=run)


def main():
    wandb.require("service")

    reference_run()

    share_run()


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
