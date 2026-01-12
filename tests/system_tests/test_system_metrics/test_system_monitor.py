from __future__ import annotations

import time

import wandb


def test_run_system_metrics(wandb_backend_spy):
    with wandb.init(
        settings=wandb.Settings(
            x_file_stream_transmit_interval=1,
            x_stats_sampling_interval=0.1,
            x_stats_buffer_size=100,
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

        # Check that system metrics buffered in wandb-core
        # are available through the Run object.
        assert len(run._system_metrics) > 0


def test_environment_data(wandb_backend_spy):
    with wandb.init(
        settings=wandb.Settings(
            x_file_stream_transmit_interval=1,
            x_stats_sampling_interval=1,
        )
    ) as run:
        # Environment metadata are collected on a best-effort basis,
        # and may take a few moments, wait for that.
        start_time = time.monotonic()
        while time.monotonic() - start_time < 30:
            with wandb_backend_spy.freeze() as snapshot:
                config = snapshot.config(run_id=run.id)
                env_data = config.get("_wandb", {}).get("value", {}).get("e")
                if env_data:
                    writer_id = list(env_data.keys())[0]
                    assert writer_id == env_data[writer_id]["writerId"]
                    break
            time.sleep(1)
        else:
            raise AssertionError("Timed out waiting for system metrics.")
