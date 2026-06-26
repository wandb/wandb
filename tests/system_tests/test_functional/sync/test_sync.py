from __future__ import annotations

import concurrent.futures
import queue
import subprocess
import time

import wandb
from tests.fixtures.wandb_backend_spy import WandbBackendSpy

_TIMEOUT_SLOW = 5  # Timeout for operations that may be slow.
_TIMEOUT_NORMAL = 1  # Timeout for operations that are probably not too slow.


def test_live_sync(wandb_backend_spy: WandbBackendSpy):
    logger_inputs = queue.Queue[str]()
    logger_outputs = queue.Queue[str]()

    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Start the logging subprocess and get the sync directory.
        executor.submit(_log_run, inputs=logger_inputs, outputs=logger_outputs)
        sync_dir = logger_outputs.get(timeout=_TIMEOUT_SLOW)

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
        logger_inputs.put("done")

        # Wait for syncing to finish successfully.
        assert sync_proc.wait(timeout=_TIMEOUT_SLOW) == 0

    # Spot-check that all data was uploaded.
    with wandb_backend_spy.freeze() as snapshot:
        run_ids = snapshot.run_ids()
        assert len(run_ids) == 1
        run_id = list(run_ids)[0]

        summary = snapshot.summary(run_id=run_id)
        assert summary["final_value"] == "done"


def _log_run(inputs: queue.Queue[str], outputs: queue.Queue[str]) -> None:
    """Log to an offline run for up to 10 seconds.

    Puts the run's sync directory on the outputs queue once the run is
    initialized, then logs until any value is received on the inputs queue,
    storing that as the "final_value" key in the run's summary.
    """

    with wandb.init(mode="offline") as run:
        outputs.put(run.settings.sync_dir)

        # Force the run to flush to disk, so that syncing may start.
        run.log({"lots_of_data": "a" * 32 * 1024})

        # Log for up to 10 seconds and return once the end signal is received.
        for i in range(100):
            run.log({"i": i})

            try:
                final_value = inputs.get(timeout=0.1)
            except queue.Empty:
                continue
            else:
                run.summary["final_value"] = final_value
                return

        raise AssertionError("Did not receive finish signal.")
