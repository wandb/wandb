#!/usr/bin/env python
"""Test parent and child processes sharing a run."""

import multiprocessing as mp

import wandb
import yea


def process_child(run):
    run.config.c2 = 22
    run.log({"s1": 21})
    run.log({"s1": 210})


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


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
