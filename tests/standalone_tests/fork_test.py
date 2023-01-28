#!/usr/bin/env python

import time
import os
import sys

import wandb

print("start", sys.stdout.write)

print("parent", os.getpid())

run = wandb.init()

pid = os.fork()

if pid > 0:
    # parent
    print("parent", os.getpid(), sys.stdout.write)
else:
    print("child", os.getpid(), sys.stdout.write)

print("both")

if pid > 0:
    time.sleep(5)
    run.finish()
