import argparse
import math
import multiprocessing as mp
import random

import wandb


def moar(run):
    run.log({"moar": random.random()})


def main(attach_id: str, eval_step: int, project: str):
    run = wandb.init(
        id=attach_id,
        project=project,
        settings=wandb.Settings(
            mode="async",
            console="off",
            _disable_machine_info=True,
            _disable_stats=True,
        ),
    )

    # run.define_metric(name="eval_step", hidden=True)  # doesn't work
    # run.define_metric(name="eval_accuracy", step_metric="eval_step")

    value = min(math.log(eval_step + 1) / 5 + random.random() / 20, 1)
    run.log(
        {
            "eval_accuracy": value,
            "eval_step": eval_step,
        },
    )

    p = mp.Process(target=moar, args=(run,))
    p.start()
    p.join()

    run.finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--attach_id", type=str, required=True)
    parser.add_argument("--project", type=str, default="igena")
    parser.add_argument("--eval_step", type=int, required=True)

    args = parser.parse_args()

    main(**vars(args))
