#!/usr/bin/env python
"""Offline runs running in different processes.

---
id: 0.offline.02-multiprocess
env:
  - WANDB_BASE_URL: https://does.not-resolve/
command:
  timeout: 20
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      metric: 10
  - :wandb:runs[0][exitcode]: 0
  - :yea:exit: 0
"""

import multiprocessing

import wandb


def log_metric(wandb_run):
    wandb_run.log({"metric": 10})


if __name__ == "__main__":
    wandb_run = wandb.init(mode="offline")

    ctx = multiprocessing.get_context("spawn")
    pool = ctx.Pool(processes=2)

    futures = []
    for _ in range(2):
        future = pool.apply_async(log_metric, args=(wandb_run,))
        futures.append(future)

    [future.get() for future in futures]
