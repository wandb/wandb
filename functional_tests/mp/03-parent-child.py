#!/usr/bin/env python
"""Test parent and child runs."""

import multiprocessing as mp
import os

import wandb
import yea


def process_child():
    run_child = wandb.init()
    run_child.config.id = "child"
    run_child.name = "child-name"

    fname = os.path.join("tmp", "03-child.txt")
    with open(fname, "w") as fp:
        fp.write("child-data")
    run_child.save(fname)

    run_child.log({"c1": 21})
    run_child.log({"c1": 22})
    run_child.finish()


def main():
    wandb.require("service")

    try:
        os.mkdir("tmp")
    except FileExistsError:
        pass

    run_parent = wandb.init()
    run_parent.config.id = "parent"
    run_parent.log({"p1": 11})
    run_parent.name = "parent-name"

    fname1 = os.path.join("tmp", "03-parent-1.txt")
    with open(fname1, "w") as fp:
        fp.write("parent-1-data")
    run_parent.save(fname1)

    # Start a new run in parallel in a child process
    p = mp.Process(target=process_child)
    p.start()

    fname2 = os.path.join("tmp", "03-parent-2.txt")
    with open(fname2, "w") as fp:
        fp.write("parent-2-data")
    run_parent.save(fname2)

    p.join()

    fname3 = os.path.join("tmp", "03-parent-3.txt")
    with open(fname3, "w") as fp:
        fp.write("parent-3-data")
    run_parent.save(fname3)

    run_parent.log({"p1": 12})
    run_parent.finish()


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
