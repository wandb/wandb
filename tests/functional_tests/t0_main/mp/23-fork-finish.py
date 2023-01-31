#!/usr/bin/env python

import os
import sys
import time

import wandb

run = wandb.init()

run.log(dict(a=1))
child_pid = os.fork()

if child_pid == 0:
    # FIXME: this might block because of an atexit hook in the forked child
    sys.exit(0)

time.sleep(3)
wait_pid, wait_exit = os.waitpid(child_pid, 0)

assert wait_pid == child_pid
assert wait_exit == 0
