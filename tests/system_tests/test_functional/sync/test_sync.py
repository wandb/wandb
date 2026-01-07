from __future__ import annotations

import multiprocessing as mp
import subprocess
import time
from multiprocessing.connection import Connection

import wandb
from tests.fixtures.wandb_backend_spy import WandbBackendSpy

_TIMEOUT_SLOW = 5  # Timeout for operations that may be slow.
_TIMEOUT_NORMAL = 1  # Timeout for operations that are probably not too slow.


def test_live_sync(wandb_backend_spy: WandbBackendSpy):
    pipe_parent, pipe_child = mp.Pipe()

    with mp.Pool() as pool:
        # Start the logging subprocess and get the sync directory.
        log_result = pool.apply_async(_log_run, (pipe_child,))
        assert pipe_parent.poll(timeout=_TIMEOUT_SLOW)
        sync_dir = pipe_parent.recv()

        # Start live syncing.
        sync_proc = subprocess.Popen(["wandb", "beta", "sync", "--live", sync_dir])

        # Wait until the upload starts, to test live functionality.
        start_time = time.monotonic()
        while time.monotonic() < start_time + _TIMEOUT_SLOW:
            with wandb_backend_spy.freeze() as snapshot:
                if snapshot.run_ids():
                    break
            time.sleep(0.1)
        else:
            raise AssertionError("Didn't start uploading.")

        # Stop logging.
        pipe_parent.send("done")

        # Wait for logging and syncing to finish successfully.
        log_result.get(timeout=_TIMEOUT_NORMAL)
        assert sync_proc.wait(timeout=_TIMEOUT_SLOW) == 0

    # Spot-check that all data was uploaded.
    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = list(run_ids)[0]

        summary = snapshot.summary(run_id=run_id)
        assert summary["final_value"] == "done"


def _log_run(pipe: Connection[str, str]) -> None:
    """Log to an offline run for up to 10 seconds.

    Puts the run's sync directory on the pipe once the run is initialized,
    then logs until any value is received on the pipe, storing that as the
    "final_value" key in the run's summary.
    """

    with wandb.init(mode="offline") as run:
        pipe.send(run.settings.sync_dir)

        # Force the run to flush to disk, so that syncing may start.
        run.log({"lots_of_data": "a" * 32 * 1024})

        # Log for up to 10 seconds and return once the end signal is received.
        for i in range(100):
            run.log({"i": i})
            if pipe.poll(timeout=0.1):
                run.summary["final_value"] = pipe.recv()
                return

        raise AssertionError("Did not receive finish signal.")
