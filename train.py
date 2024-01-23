import argparse
import math
import os
import random
import subprocess
import time

import tqdm

import wandb


def main(
    project: str = "igena",
    sleep: int = 1,
):
    run = wandb.init(
        project=project,
        settings=wandb.Settings(
            init_timeout=60,
            mode="shared",
            # console="off",
            # _disable_machine_info=True,
            # _disable_stats=False,
            # _disable_stats=True,
            _stats_sample_rate_seconds=1,
            _stats_samples_to_average=1,
            _stats_disk_paths=["/System/Volumes/Data"],
            # _stats_buffer_size=100 if symon else 0,
            disable_job_creation=True,
        ),
        # sync_tensorboard=tensorboard or None,
    )
    print("run_id:", run.id)

    run.define_metric(name="loss", step_metric="train_step")
    run.define_metric(name="eval_accuracy", step_metric="eval_step")

    bar = tqdm.tqdm()
    train_step = 0
    eval_step = 0
    while True:
        try:
            value = math.exp(-train_step / 100) + random.random() / 20
            run.log(
                {
                    "train_step": train_step,
                    "loss": value,
                }
            )
            bar.update(1)
            train_step += 1
            time.sleep(sleep)

            # kick-off evaluation
            if train_step % 20 == 0:
                subprocess.run(
                    [
                        "python",
                        "eval.py",
                        "--attach_id",
                        run.id,
                        "--eval_step",
                        str(eval_step),
                    ],
                    env={**os.environ, **{"WANDB_SERVICE": ""}},
                )
                eval_step += 1

        except KeyboardInterrupt:
            bar.close()
            break

    run.finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--project", type=str, default="igena")
    parser.add_argument("--sleep", type=int, default=1)

    args = parser.parse_args()

    main(**vars(args))
