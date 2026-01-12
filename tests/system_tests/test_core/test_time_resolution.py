from __future__ import annotations

import time

import wandb


def test_log(wandb_backend_spy):
    """Make sure log is generating history with subsecond resolution."""
    before = time.time()
    with wandb.init() as run:
        for i in range(10):
            run.log(dict(k=i))
            time.sleep(0.000010)  # 10 us
    after = time.time()

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)

        timestamps = [step["_timestamp"] for step in history.values()]
        runtimes = [step["_runtime"] for step in history.values()]

        assert len(history) == 10
        assert any(timestamp % 1 > 0 for timestamp in timestamps)
        assert any(runtime % 1 > 0 for runtime in runtimes)
        assert all(
            before <= timestamp and timestamp <= after  #
            for timestamp in timestamps
        )
        assert all(
            0 <= runtime and runtime <= after - before  #
            for runtime in runtimes
        )
