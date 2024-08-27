#!/usr/bin/env python
"""Append two offline runs."""

import subprocess
import sys

import wandb

run = wandb.init(mode="offline")
sync_dir_1 = run.settings.sync_dir
run_id = run.id
run.log(dict(m1=1), step=1)
run.log(dict(m1=2), step=2)
run.log(dict(m2=2), step=3)
run.finish()

run = wandb.init(mode="offline", id=run_id)
sync_dir_2 = run.settings.sync_dir
run.log(dict(m1=11), step=11)
run.log(dict(m1=12), step=12)
run.log(dict(m2=4), step=13)
run.finish()

wandb_sync_cmd = ["wandb", "sync"]

output1 = subprocess.check_output(wandb_sync_cmd + [f"{sync_dir_1}"])
output1 = output1.decode(sys.stdout.encoding)
for line in output1.splitlines():
    print("sync1:", line)

output2 = subprocess.check_output(wandb_sync_cmd + ["--append", f"{sync_dir_2}"])
output2 = output2.decode(sys.stdout.encoding)
for line in output2.splitlines():
    print("sync2:", line)
