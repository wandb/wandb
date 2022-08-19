#!/usr/bin/env python
"""Test attach runs."""

import multiprocessing as mp

import wandb
import yea


def process_child(attach_id):
    run_child = wandb.attach(attach_id=attach_id)
    run_child.config.c2 = 22
    run_child.log({"s1": 21})
    run_child.log({"s2": 22})
    run_child.log({"s3": 23})
    print("child output")


def main():
    wandb.require("service")

    run = wandb.init()
    print("parent output")
    run.config.c1 = 11
    run.log(dict(s2=12, s4=14))

    # Start a new run in parallel in a child process
    attach_id = run.id
    p = mp.Process(target=process_child, kwargs=dict(attach_id=attach_id))
    p.start()
    p.join()

    # run can still be logged to after join (and eventually anytime?)
    run.log(dict(s3=13))
    print("more output from parent")


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
