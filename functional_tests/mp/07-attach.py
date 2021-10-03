#!/usr/bin/env python
"""Test attaach runs.

---
id: 0.mp.4-attach
plugin:
    - wandb
parametrize:
  permute:
    - :yea:start_method:
      - spawn
      - forkserver
assert:
    - :wandb:runs_len: 1
    - :wandb:runs[0][summary][s1]: 21
    - :wandb:runs[0][summary][s2]: 22
    - :wandb:runs[0][summary][s3]: 13
    - :wandb:runs[0][summary][s4]: 14
    - :wandb:runs[0][config][c1]: 11
    - :wandb:runs[0][config][c2]: 22
"""

import multiprocessing as mp

import wandb
import yea


def process_child(attach_id):
    run_child = wandb.init(attach=attach_id)
    run_child.config.c2 = 22
    run_child.log({"s1": 21})
    run_child.log({"s2": 22})
    run_child.log({"s3": 23})


def main():
    wandb.require("concurrency")

    run = wandb.init()
    run.config.c1 = 11
    run.log(dict(s2=12, s4=14))

    # Start a new run in parallel in a child process
    attach_id = run._attach_id
    p = mp.Process(target=process_child, kwargs=dict(attach_id=attach_id))
    p.start()
    p.join()

    # run can still be logged to after join (and eventually anytime?)
    run.log(dict(s3=13))


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
