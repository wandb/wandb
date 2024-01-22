import argparse
import random

import wandb


def main(attach_id: str, eval_step: int):
    run = wandb.attach(
        run_id=attach_id,
        settings=wandb.Settings(
            mode="async",
            console="off",
            _disable_machine_info=True,
            _disable_stats=True,
        ),
    )

    run.log(
        {
            "eval_accuracy": random.random(),
            "eval_step": eval_step,
        },
    )

    # TODO: ??
    # run.detach()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--attach_id", type=str, required=True)
    parser.add_argument("--eval_step", type=int, required=True)

    args = parser.parse_args()

    main(**vars(args))
