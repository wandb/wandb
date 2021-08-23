#!/usr/bin/env python
"""Test parent and child runs."""

import multiprocessing as mp

import wandb
import yea


def process_child():
    run_child = wandb.init()
    run_child.config.id = "child"
    run_child.log({"c1": 21})
    run_child.log({"c1": 22})
    run_child.finish()


def main():
    wandb.require("concurrency")

    run_parent = wandb.init()
    run_parent.config.id = "parent"
    run_parent.log({"p1": 11})

    # Start a new run in parallel in a child process
    p = mp.Process(target=process_child)
    p.start()

    run_parent.log({"p1": 12})
    run_parent.finish()
    p.join()


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
