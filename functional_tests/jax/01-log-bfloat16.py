#!/usr/bin/env python
"""Base case - main process init/finish.
"""
import jax.numpy as jnp
import wandb

if __name__ == "__main__":
    run = wandb.init()

    m1 = jnp.array(1., dtype=jnp.float32)
    run.log(dict(m1=m1))
    m2 = jnp.array(2., dtype=jnp.bfloat16)
    run.log(dict(m2=m2))
    run.finish()
