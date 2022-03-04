import multiprocessing as mp
import os

import numpy as np
import wandb
import yea


def process_child(run):
    rng = np.random.default_rng(os.getpid())
    height = width = 2

    media = []
    for _ in range(2):
        media.append(wandb.Image(rng.random((height, width))))
        run.log({"media": media}, commit=False)
    # print(run._settings.files_dir)

    run.log({"x": 1})


def main():
    wandb.require("service")
    wandb.setup()
    run = wandb.init()
    # run.log({"a": 1})
    # Start a new run in parallel in a child process
    processes = []
    for _ in range(2):
        p = mp.Process(target=process_child, kwargs=dict(run=run))
        processes.append(p)

    for p in processes:
        p.start()

    for p in processes:
        p.join()


if __name__ == "__main__":
    yea.setup()  # Use ":yea:start_method:" to set mp.set_start_method()
    main()
