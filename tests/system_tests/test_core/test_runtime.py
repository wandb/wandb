"""Tests for the automatic '_runtime' metric."""

import wandb

from tests.fixtures.wandb_backend_spy import WandbBackendSpy


def test_runtime_in_history(wandb_backend_spy: WandbBackendSpy):
    with wandb.init() as run:
        run.log({"x": 1})

    with wandb_backend_spy.freeze() as snapshot:
        history = snapshot.history(run_id=run.id)
        assert "_runtime" in history[0]

        # Check that the unit is in seconds (rather than milliseconds or less).
        assert 0 < history[0]["_runtime"] < 2


def test_runtime_summary_on_finish(wandb_backend_spy: WandbBackendSpy):
    with wandb.init() as run:
        pass  # Should upload a runtime on finish despite lack of history.

    with wandb_backend_spy.freeze() as snapshot:
        summary = snapshot.summary(run_id=run.id)

        assert "_runtime" in summary
        assert "_wandb" in summary
        assert "runtime" in summary["_wandb"]
        assert summary["_runtime"] == summary["_wandb"]["runtime"]

        # Check that the unit is in seconds (rather than milliseconds or less).
        assert 0 < summary["_runtime"] < 2
