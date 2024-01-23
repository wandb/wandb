import argparse
import math
import random

import wandb


def main(attach_id: str, eval_step: int, project: str):
    run = wandb.init(
        id=attach_id,
        project=project,
        settings=wandb.Settings(
            mode="shared",
            console="off",
            _disable_machine_info=True,
            _disable_stats=True,
            disable_job_creation=True,
        ),
    )
    # print("hi, I'm eval.py")

    value = min(math.log(eval_step + 1) / 5 + random.random() / 20, 1)
    run.log(
        {
            "eval_accuracy": value,
            "eval_step": eval_step,
        },
    )

    run.finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--attach_id", type=str, required=True)
    parser.add_argument("--project", type=str, default="igena")
    parser.add_argument("--eval_step", type=int, required=True)

    args = parser.parse_args()

    main(**vars(args))
