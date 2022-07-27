#!/usr/bin/env python
"""Test parent and child processes sharing a run. Synchronize worker process to insure the order of logging."""

import multiprocessing as mp

import wandb
import yea


def worker_process(run, i):
    with i.get_lock():
        i.value += 1
        run.log({"i": i.value})


def main():
    wandb.require("service")
    run = wandb.init()

    counter = mp.Value("i", 0)
    workers = [
        mp.Process(target=worker_process, kwargs=dict(run=run, i=counter))
        for _ in range(4)
    ]

    for w in workers:
        w.start()

    for w in workers:
        w.join()


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
