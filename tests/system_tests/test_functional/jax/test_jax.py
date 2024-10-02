import jax.numpy as jnp
import pytest


@pytest.mark.wandb_core_only
def test_log_bfloat16(wandb_init, relay_server):
    with relay_server() as relay:
        run = wandb_init()
        m1 = jnp.array(1.0, dtype=jnp.float32)
        m2 = jnp.array(2.0, dtype=jnp.bfloat16)
        m3 = jnp.array([3.0, 4.0], dtype=jnp.bfloat16)
        run.log(dict(m1=m1, m2=m2, m3=m3))
        run.finish()

    context = relay.context
    run_ids = context.get_run_ids()
    assert len(run_ids) == 1
    run_id = run_ids[0]

    summary = context.get_run_summary(run_id)
    assert summary["m1"] == 1
    assert summary["m2"] == 2
    assert summary["m3"] == [3, 4]
