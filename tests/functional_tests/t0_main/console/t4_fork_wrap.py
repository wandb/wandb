#!/usr/bin/env python

import os

import wandb

print("before")

run = wandb.init()

child_pid = os.fork()

if child_pid > 0:
    print("parent")
else:
    print("child")
print("both")

if child_pid == 0:
    # note, we need to force exit because the fork process has atexit waiting for service shutdown
    os._exit(0)

wait_pid, wait_exit = os.waitpid(child_pid, 0)
run.finish()

assert wait_pid == child_pid
assert wait_exit == 0
