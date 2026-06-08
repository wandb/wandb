import functools
import multiprocessing
import pathlib
import subprocess

import pytest
import wandb

from tests.fixtures.wandb_backend_spy import WandbBackendSpy


@pytest.mark.parametrize(
    "start_method",
    ["spawn", "forkserver"],
)
def test_share_child_base(
    wandb_backend_spy: WandbBackendSpy,
    start_method: str,
):
    script_path = pathlib.Path(__file__).parent / "share_child_base.py"
    subprocess.run(
        ("python", str(script_path), "--start-method", start_method),
        check=True,
    )

    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1

        run_id = run_ids.pop()
        history = snapshot.history(run_id=run_id)
        assert history[0]["s1"] == 11
        assert history[1]["s1"] == 21

        config = snapshot.config(run_id=run_id)
        assert config["c1"]["value"] == 11
        assert config["c2"]["value"] == 22


def _log_and_read_step(run: wandb.Run, value: str) -> int:
    run.log({"value": value})
    return run.step


def test_attach_step():
    """Test the value of run.step in attached runs."""
    # Within the test worker, only "spawn" is guaranteed to work.
    #
    # When using the "forkserver" method, child processes inherit the
    # WANDB_SERVICE value snapshotted at the fork server's start time.
    # The fork server is reused between tests, but the WANDB_SERVICE value
    # changes after each test. Child processes depend on having the correct
    # value to connect to wandb-core.
    ctx = multiprocessing.get_context("spawn")

    with (
        wandb.init(mode="offline") as run,
        ctx.Pool(processes=2) as pool,
    ):
        steps = pool.map(
            functools.partial(_log_and_read_step, run),
            ("logger1", "logger2"),
        )

    # `run.step` happens after 1 `log()` in both cases:
    assert steps[0] >= 1
    assert steps[1] >= 1

    # `run.step` happens after 2 `log()` in at least one of the cases:
    assert 2 in steps
