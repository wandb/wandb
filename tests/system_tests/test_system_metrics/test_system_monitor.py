import time

import pytest
import wandb


@pytest.mark.wandb_core_only
def test_run_system_metrics(wandb_backend_spy, test_settings):
    with wandb.init(
        settings=test_settings(
            wandb.Settings(
                x_file_stream_transmit_interval=1,
                x_stats_sampling_interval=1,
                x_stats_buffer_size=100,
            )
        )
    ) as run:
        # Wait for the first metrics to be logged.
        start_time = time.monotonic()
        while time.monotonic() - start_time < 60:
            with wandb_backend_spy.freeze() as snapshot:
                if len(snapshot.system_metrics(run_id=run.id)) > 0:
                    break
            time.sleep(1)
        else:
            raise AssertionError("Timed out waiting for system metrics.")

        assert len(run._system_metrics) > 0
