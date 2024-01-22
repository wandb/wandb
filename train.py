import argparse
import random
import time

import wandb


def main(
    project: str = "igena",
    sleep: int = 1,
):
    run = wandb.init(
        project=project,
        settings=wandb.Settings(
            init_timeout=60,
            mode="async",
            console="off",
            # _disable_machine_info=True,
            # _disable_stats=False,
            # _disable_stats=True,
            _stats_sample_rate_seconds=1,
            _stats_samples_to_average=1,
            _stats_disk_paths=["/System/Volumes/Data"],
            # _stats_buffer_size=100 if symon else 0,
            # _async_upload_concurrency_limit=5,
            disable_job_creation=True,
        ),
        # sync_tensorboard=tensorboard or None,
    )
    print("run_id:", run.id)

    while True:
        try:
            print(">>>>logging...")
            run.log({"loss": random.random()})
            time.sleep(sleep)
        except KeyboardInterrupt:
            break

    run.finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--project", type=str, default="igena")
    parser.add_argument("--sleep", type=int, default=1)

    args = parser.parse_args()

    main(**vars(args))
