import time


def test_run_system_metrics(wandb_init, relay_server, test_settings):
    with relay_server() as relay:
        run = wandb_init(
            settings=test_settings(
                dict(
                    _stats_sample_rate_seconds=1,
                    _stats_samples_to_average=1,
                    _stats_buffer_size=100,
                )
            ),
        )

        # Wait for the first metrics to be logged
        # If there's an issue, the test will eventually time out and fail
        while not len(relay.context.get_file_contents("wandb-events.jsonl")):
            time.sleep(1)

        assert len(run._system_metrics) > 0
        print(run._system_metrics)

        run.finish()
