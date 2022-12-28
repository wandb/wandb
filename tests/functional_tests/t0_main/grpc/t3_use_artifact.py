#!/usr/bin/env python

import os

import wandb

# Temporary environment variable for testing grpc service mode
os.environ["WANDB_SERVICE_TRANSPORT"] = "grpc"

wandb.require("service")
run = wandb.init()
artifact = wandb.Artifact("my-artifact", type="dataset")
run.use_artifact(artifact)
print("somedata")
run.log(dict(m1=1))
run.log(dict(m2=2))
