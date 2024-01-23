import argparse
import math
import os
import pathlib
import random
import subprocess
import time

import tqdm
import wandb


def main(
    project: str = "igena",
    sleep: int = 1,
    num_steps: int = 10,
    eval_rate: int = 4,
):
    run = wandb.init(
        project=project,
        settings=wandb.Settings(
            init_timeout=60,
            mode="shared",
            _stats_sample_rate_seconds=1,
            _stats_samples_to_average=1,
            _stats_disk_paths=["/System/Volumes/Data"],
            disable_job_creation=True,
        ),
    )
    print("run_id:", run.id)

    run.define_metric(name="loss", step_metric="train_step")
    run.define_metric(name="eval_accuracy", step_metric="eval_step")

    bar = tqdm.tqdm()
    train_step = 0
    eval_step = 0
    while train_step < num_steps:
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
            if train_step % eval_rate == 0:
                subprocess.check_output(
                    [
                        "python",
                        pathlib.Path(__file__).parent / "eval.py",
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
    parser.add_argument("--num_steps", type=int, default=10)
    parser.add_argument("--eval_rate", type=int, default=4)

    args = parser.parse_args()

    main(**vars(args))
