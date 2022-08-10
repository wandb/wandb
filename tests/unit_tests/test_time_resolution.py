"""
time resolution full tests.
"""

import time

import pytest


def test_log(relay_server, wandb_init):
    """Make sure log is generating history with subsecond resolution."""

    with relay_server() as relay:
        before = time.time()
        run = wandb_init()
        run_id = run.id
        for i in range(10):
            run.log(dict(k=i))
            time.sleep(0.000010)  # 10 us
        run.finish()
        after = time.time()

    history = relay.context.get_run_history(run_id, include_private=True)

    assert history.shape[0] == 10
    assert any(history["_timestamp"] % 1 > 0)
    assert any(history["_runtime"] % 1 > 0)
    assert all(before <= history["_timestamp"]) and all(history["_timestamp"] <= after)
    assert all(0 <= history["_runtime"]) and all(history["_runtime"] <= after - before)


@pytest.mark.xfail(reason="TODO: this test is non-deterministic and sometimes fails")
def test_stats(relay_server, wandb_init):
    with relay_server() as relay:
        before = time.time()
        run = wandb_init(
            settings={"_stats_sample_rate_seconds": 0.6, "_stats_samples_to_average": 2}
        )
        time.sleep(3)
        run.finish()
        after = time.time()

    stats = relay.context.get_run_stats(run.id)

    assert len(stats) > 1
    # assert any(stats["_timestamp"])
    # assert any(stats["_runtime"])
    assert all(before <= stats["_timestamp"]) and all(stats["_timestamp"] <= after)
    assert all(0 <= stats["_runtime"]) and all(stats["_runtime"] <= after - before)
