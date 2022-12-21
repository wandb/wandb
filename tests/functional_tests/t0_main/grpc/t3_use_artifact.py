#!/usr/bin/env python

import os

import wandb

# Temporary environment variable for testing grpc service mode
os.environ["WANDB_SERVICE_TRANSPORT"] = "grpc"

wandb.require("service")
wandb.init()
artifact = wandb.Artifact("my-artifact", type="dataset")
wandb.run.use_artifact(artifact)
print("somedata")
wandb.log(dict(m1=1))
wandb.log(dict(m2=2))
wandb.finish()
