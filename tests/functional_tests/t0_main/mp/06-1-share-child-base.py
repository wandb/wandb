#!/usr/bin/env python
"""Test parent and child processes sharing a run.

Compare to a run in a single process, base usage of `run.log`.
"""

import multiprocessing as mp

import wandb
import yea


def process_parent():
    run = wandb.init()
    assert run == wandb.run

    run.config.c1 = 11
    run.log({"s1": 11})
    return run


def process_child(run):
    run.config.c2 = 22
    run.log({"s1": 21})


def reference_run():
    run = process_parent()
    process_child(run)
    run.finish()


def share_run():
    run = process_parent()
    p = mp.Process(target=process_child, kwargs=dict(run=run))
    p.start()
    p.join()
    run.finish()


def main():
    reference_run()
    share_run()


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
