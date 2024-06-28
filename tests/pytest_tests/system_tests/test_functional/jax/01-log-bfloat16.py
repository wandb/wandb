#!/usr/bin/env python
"""Log a bfloat16 tensor."""

import jax.numpy as jnp
import wandb

if __name__ == "__main__":
    run = wandb.init()
    m1 = jnp.array(1.0, dtype=jnp.float32)
    m2 = jnp.array(2.0, dtype=jnp.bfloat16)
    m3 = jnp.array([3.0, 4.0], dtype=jnp.bfloat16)
    run.log(dict(m1=m1, m2=m2, m3=m3))
    run.finish()
