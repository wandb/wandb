#!/usr/bin/env python
"""Enable tracelog to logger, make sure there are logs.

---
id: 0.tracelog.01-simple
plugin:
  - wandb
assert:
  - :wandb:runs_len: 1
  - :wandb:runs[0][config]: {}
  - :wandb:runs[0][summary]:
      m1: 1
      m2: 2
  - :wandb:runs[0][exitcode]: 0
  - :op:contains:
    - :wandb:runs[0][telemetry][3]  # feature
    - 2  # finish
"""

import os

import wandb

os.environ["WANDB_TRACELOG"] = "logger"
run = wandb.init()
run.log(dict(m1=1))
run.log(dict(m2=2))

# NOTE: internal stuff for testing, could break in the future
debug_log_user = run._settings.log_user
debug_log_internal = run._settings.log_internal
print(f"Log user: {debug_log_user}")
print(f"Log internal: {debug_log_internal}")

run.finish()

# Simple validation that log files exist, could move to yea in the future
trace_log_str = "TRACELOG(1)"
debug_log_internal_count = 0
with open(debug_log_user) as f:
    debug_log_user_count = f.read().count(trace_log_str)
with open(debug_log_internal) as f:
    debug_log_internal_count = f.read().count(trace_log_str)
print(f"Log user count: {debug_log_user_count}")
print(f"Log internal count: {debug_log_internal_count}")
assert debug_log_user_count > 10
assert debug_log_internal_count > 10
