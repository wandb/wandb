from __future__ import annotations

import jax.numpy as jnp
import wandb


def test_log_bfloat16(wandb_backend_spy):
    run = wandb.init()
    m1 = jnp.array(1.0, dtype=jnp.float32)
    m2 = jnp.array(2.0, dtype=jnp.bfloat16)
    m3 = jnp.array([3.0, 4.0], dtype=jnp.bfloat16)
    run.log(dict(m1=m1, m2=m2, m3=m3))
    run.finish()

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        assert run.id in run_ids

        summary = snapshot.summary(run_id=run.id)
        assert summary["m1"] == 1
        assert summary["m2"] == 2
        assert summary["m3"] == [3, 4]
