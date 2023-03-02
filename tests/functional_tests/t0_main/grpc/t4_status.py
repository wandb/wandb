#!/usr/bin/env python

import os

import wandb

# Temporary environment variable for testing grpc service mode
os.environ["WANDB_SERVICE_TRANSPORT"] = "grpc"

run = wandb.init()
print("somedata")
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
status = run.status()
print("STATUS", status)
wandb.finish()
