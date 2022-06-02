#!/usr/bin/env python
"""Debug log to stdout.

---
id: 0.debug.01-tracelog-stdout
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      m1: 1
      m2: 2
  # TODO: change this test to use logger and add func to yea
  #       to pull in logger info.
  # - :op:contains_regex:
  #   - :wandb:runs[0][output][stderr]
  #   - "queue   MainThread       history"
  - :wandb:runs[0][exitcode]: 0
"""

import os

import wandb

os.environ["WANDB_TRACELOG"] = "stdout"
wandb.require("service")
wandb.init()
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
