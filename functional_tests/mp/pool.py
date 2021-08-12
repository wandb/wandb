#!/usr/bin/env python
"""mp-pool - N runs in parallel

---
id: 3.0.2
plugin:
  - wandb
parametrize:
  permute:
    - :yea:start_method:
      - fork
      - spawn
      - forkserver
var:
  - run0:
      :fn:find:
      - item
      - :wandb:runs
      - :item[config][id]: 0
  - run1:
      :fn:find:
      - item
      - :wandb:runs
      - :item[config][id]: 1
  - run2:
      :fn:find:
      - item
      - :wandb:runs
      - :item[config][id]: 2
  - run3:
      :fn:find:
      - item
      - :wandb:runs
      - :item[config][id]: 3
assert:
  - :wandb:runs_len: 4
  - :run0[config]: {id: 0}
  - :run0[summary]: {s: 0}
  - :run0[exitcode]: 0
  - :run1[config]: {id: 1}
  - :run1[summary]: {s: 1}
  - :run1[exitcode]: 0
  - :run2[config]: {id: 2}
  - :run2[summary]: {s: 2}
  - :run2[exitcode]: 0
  - :run3[config]: {id: 3}
  - :run3[summary]: {s: 3}
  - :run3[exitcode]: 0
"""

import multiprocessing as mp
import os
import time

import wandb


def do_run(num):
    time.sleep(1)
    print("TEST: start", num)
    run = wandb.init()
    print("TEST: init", num)
    run.config.id = num
    time.sleep(1)
    run.log(dict(s=num))
    time.sleep(1)
    print("TEST: finish", num)
    run.finish()
    time.sleep(1)
    print("TEST: end", num)
    return num


def main():
    wandb.require("multiprocessing")

    num_proc = 4
    pool = mp.Pool(processes=num_proc)
    result = pool.map_async(do_run, range(num_proc))
    data = result.get(60)
    print("TEST: Out", data)


def setup_mp():
    # TODO: Move to yea
    perm = os.environ.get("YEA_PERMUTE_VAL")
    if not perm:
        return
    mp.set_start_method(perm)


if __name__ == "__main__":
    setup_mp()
    main()
