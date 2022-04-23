#!/usr/bin/env python

import wandb
import torch

wandb.require("service")
run = wandb.init()
print("somedata")

run.log(dict(m1=torch.tensor(1.0)))

import jax.numpy as jnp

run.log(dict(m2=jnp.array(2.0, dtype=jnp.float32)))
