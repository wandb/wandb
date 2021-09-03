#!/usr/bin/env python
"""Test parent and child processes sharing a run.

---
id: 0.mp.4-sharechild
plugin:
  - wandb
tag:
  skip: True
env:
  - WANDB_CONSOLE: "off"
parametrize:
  permute:
    - :yea:start_method:
      - spawn
      - forkserver
assert:
  - :wandb:runs_len: 2
  - :wandb:runs[0][config]: {id: parent}
  - :wandb:runs[0][summary]: {p1: 12}
  - :wandb:runs[0][exitcode]: 0
  - :wandb:runs[1][config]: {id: child}
  - :wandb:runs[1][summary]: {c1: 22}
  - :wandb:runs[1][exitcode]: 0

"""

import multiprocessing as mp

import wandb
import yea


def process_child(run):
    run.config.c2 = 22
    run.log({"s1": 21})
    run.log({"s1": 210})


def main():
    wandb.require("concurrency")

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
